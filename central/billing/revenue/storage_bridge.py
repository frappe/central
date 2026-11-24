# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from collections.abc import Callable

import frappe

from central.billing.revenue.bundled_buckets import bundled_buckets
from central.billing.revenue.usage_ledger import utc_today, write_days
from central.integrations.object_storage import ObjectStorageClient, ObjectStorageNotFound
from central.services.doctype.service.service import STORAGE_METER, STORAGE_SERVICE, is_read_by_central
from central.services.doctype.team_service.team_service import billed_subjects

PAGE_SIZE = 100
# A run's counters outlive any page that is still queued, then expire on their own.
RUN_TTL_SECONDS = 6 * 60 * 60
LOGGED_FAILURES = 50


def read_storage_usage() -> int:
	"""Hourly, until Cargo reports usage itself: read every bucket and keep each day's peak."""
	if not is_read_by_central(STORAGE_SERVICE):
		return 0
	run = frappe.generate_hash(length=12)
	# Team buckets and servers' backup buckets are read by their own page jobs.
	jobs = {"read_page": pages(billed_buckets()), "read_bundled_page": pages(bundled_buckets_by_region())}
	_start_regions(run, jobs)
	return _enqueue_pages(run, jobs)


def read_page(run: str, region: str, names: list[str]) -> int:
	"""Read one page of a region's team buckets and write their days."""
	return _read_and_write(run, region, *team_bucket_reader(names))


def read_bundled_page(run: str, region: str, names: list[str], day=None) -> int:
	"""Read one page of a region's servers' backup buckets and write their days."""
	# `day` is kept only for jobs queued with it; the reader takes the day it reads.
	return _read_and_write(run, region, *bundled_bucket_reader(names))


def team_bucket_reader(names: list[str]) -> tuple[list[str], Callable[[str], dict]]:
	"""A page's team buckets, and the reader of one into today's Usage Day row."""
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)
	return names, lambda name: _reading(name, meter)


def bundled_bucket_reader(names: list[str]) -> tuple[list[str], Callable[[str], dict]]:
	"""A page's backup buckets that bill today, and the reader of one into today's Usage Day row."""
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)
	# The reading is what the bucket holds now, so it belongs to the day it is read, even for a
	# page queued before midnight.
	day = utc_today()
	# That day bills a bucket whose server billed at any point of it, even one paused or resized
	# off storage before the page ran.
	buckets = bundled_buckets(names, day)
	billed = [name for name in names if name in buckets]
	return billed, lambda name: _bundled_reading(buckets[name], meter, day)


def _read_and_write(run: str, region: str, names: list[str], read) -> int:
	readings, failed = {}, []
	for name in names:
		# One bucket's failure, of any kind, must not stop the page's other buckets.
		try:
			readings[name] = read(name)
		except Exception as error:
			failed.append(f"{name}: {error!r}")
	try:
		# A day another worker wrote meanwhile is written again by the next hour's reading.
		written = write_days(list(readings.values())).count
	except Exception as error:
		# The page still counts down, so the region's summary is written; the job itself still fails.
		failed += [f"{name}: page failed: {type(error).__name__}" for name in readings]
		RegionRead(run, region).finish_page(failed, crashed=True)
		raise
	RegionRead(run, region).finish_page(failed)
	return written


def pages(buckets: dict[str, list[str]]) -> dict[str, list[list[str]]]:
	"""Each region's bucket names, in pages."""
	return {
		region: [names[start : start + PAGE_SIZE] for start in range(0, len(names), PAGE_SIZE)]
		for region, names in buckets.items()
	}


def _start_regions(run: str, jobs: dict) -> None:
	"""Count each region's pages of every kind on one counter, so its last page logs once."""
	counts: dict[str, int] = {}
	for pages in jobs.values():
		for region, region_pages in pages.items():
			counts[region] = counts.get(region, 0) + len(region_pages)
	for region, count in counts.items():
		RegionRead(run, region).start(count)


def _enqueue_pages(run: str, jobs: dict) -> int:
	from central.billing.revenue.invoicing.run import billing_queue

	queued = 0
	for method, pages in jobs.items():
		for region, region_pages in pages.items():
			for page in region_pages:
				frappe.enqueue(
					f"central.billing.revenue.storage_bridge.{method}",
					queue=billing_queue(),
					run=run,
					region=region,
					names=page,
				)
				queued += len(page)
	return queued


def bundled_buckets_by_region() -> dict[str, list[str]]:
	"""Every server's backup bucket that bills, by region."""
	regions: dict[str, list[str]] = {}
	for name, bucket in bundled_buckets().items():
		regions.setdefault(bucket.region, []).append(name)
	return regions


def billed_buckets() -> dict[str, list[str]]:
	"""Every bucket that bills a subscription, by region. Suspended ones still hold data."""
	regions: dict[str, list[str]] = {}
	for bucket in billed_subjects(STORAGE_SERVICE).values():
		regions.setdefault(bucket.region, []).append(bucket.name)
	return regions


class RegionRead:
	"""One run's read of one region, counted across its page jobs in the cache."""

	def __init__(self, run: str, region: str):
		self.region = region
		# The list goes through the cache's own methods, which add the site prefix; the counter needs
		# raw set and decr, which do not, so its key is prefixed here.
		self.errors = f"storage_read:{run}:{region}:errors"
		self.pages = frappe.cache.make_key(f"storage_read:{run}:{region}:pages")

	def start(self, pages: int) -> None:
		# nosemgrep: frappe-cache-breaks-multitenancy -- make_key adds the site prefix; decr needs a raw int.
		frappe.cache.set(self.pages, pages, ex=RUN_TTL_SECONDS)

	def finish_page(self, failed: list[str], crashed: bool = False) -> None:
		"""Count the page's failures; the region's last page logs them all once."""
		# Failures are pushed before the page counter drops, so the last page sees every one.
		for line in failed:
			frappe.cache.rpush(self.errors, line)
		if failed:
			frappe.cache.expire_key(self.errors, RUN_TTL_SECONDS)
		if frappe.cache.decr(self.pages) == 0:
			self._log_failures(crashed)

	def _log_failures(self, crashed: bool) -> None:
		count = frappe.cache.llen(self.errors)
		if count:
			lines = [
				frappe.safe_decode(line) for line in frappe.cache.lrange(self.errors, 0, LOGGED_FAILURES - 1)
			]
			frappe.log_error(
				title=f"Storage usage: {count} bucket(s) not read in {self.region}",
				message="\n".join(lines),
				reference_doctype="Region",
				reference_name=self.region,
				# A crashed page's job rolls back its transaction, so its log must not depend on it.
				defer_insert=crashed,
			)
		frappe.cache.delete_value(self.errors)
		frappe.cache.delete(self.pages)


def _reading(name: str, meter) -> dict:
	bucket = frappe.get_doc("Team Service", name)
	used = frappe.utils.flt(bucket.get_usage().get("used_bytes"))
	return meter.get_day_row(bucket, utc_today(), used, as_of=frappe.utils.now_datetime())


def _bundled_reading(bucket, meter, day) -> dict:
	"""What the bucket holds, and what its server's plan includes that day."""
	try:
		usage = ObjectStorageClient.from_region(bucket.region).get_usage(bucket.external_id)["usage"]
	except ObjectStorageNotFound:
		# The bucket was never attached, so it holds nothing.
		usage = {}
	used = frappe.utils.flt(usage.get("used_bytes"))
	return meter.get_day_row(bucket, day, used, included=bucket.included, as_of=frappe.utils.now_datetime())
