# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.revenue.bundled_buckets import bundled_buckets
from central.billing.revenue.usage_ledger import utc_today, write_days
from central.integrations.object_storage import ObjectStorageClient, ObjectStorageNotFound
from central.services.doctype.service.service import STORAGE_METER, STORAGE_SERVICE
from central.services.doctype.team_service.team_service import billed_subjects

PAGE_SIZE = 100
# A run's counters outlive any page that is still queued, then expire on their own.
RUN_TTL_SECONDS = 6 * 60 * 60
LOGGED_FAILURES = 50


def read_storage_usage() -> int:
	"""Hourly, until Cargo reports usage itself: read every bucket and keep each day's peak."""
	from central.billing.revenue.invoicing.run import billing_queue

	if not frappe.db.get_value("Service", STORAGE_SERVICE, "central_reads"):
		return 0
	run = frappe.generate_hash(length=12)
	regions = _pages_by_region()
	for region, pages in regions.items():
		RegionRead(run, region).start(len(pages))
		for page, bundled in pages:
			frappe.enqueue(
				"central.billing.revenue.storage_bridge.read_page",
				queue=billing_queue(),
				run=run,
				region=region,
				names=page,
				bundled=bundled,
			)
	return sum(len(page) for pages in regions.values() for page, _bundled in pages)


def read_page(run: str, region: str, names: list[str], bundled: bool = False) -> int:
	"""Read one page of a region's buckets and write their days."""
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)
	read = _bundled_reader(names, meter) if bundled else lambda name: _reading(name, meter)
	readings, failed = {}, []
	for name in names:
		# One bucket's failure, of any kind, must not stop the page's other buckets.
		try:
			if (row := read(name)) is not None:
				readings[name] = row
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


def _pages_by_region() -> dict[str, list[tuple[list[str], bool]]]:
	"""Each region's pages of team buckets and of servers' backup buckets, as (names, bundled)."""
	bundled: dict[str, list[str]] = {}
	for name, bucket in bundled_buckets().items():
		bundled.setdefault(bucket.region, []).append(name)
	regions: dict[str, list] = {}
	for is_bundled, buckets in ((False, billed_buckets()), (True, bundled)):
		for region, names in buckets.items():
			regions.setdefault(region, []).extend(
				(names[start : start + PAGE_SIZE], is_bundled) for start in range(0, len(names), PAGE_SIZE)
			)
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


def _bundled_reader(names: list[str], meter):
	"""Reads a server's backup bucket by name; one whose server stopped billing reads as None."""
	buckets = bundled_buckets(names)
	return lambda name: _bundled_reading(buckets[name], meter) if name in buckets else None


def _bundled_reading(bucket, meter) -> dict:
	"""What the bucket holds, and what its server's plan includes that day."""
	try:
		usage = ObjectStorageClient.from_region(bucket.region).get_usage(bucket.external_id)["usage"]
	except ObjectStorageNotFound:
		# The bucket was never attached, so it holds nothing.
		usage = {}
	used = frappe.utils.flt(usage.get("used_bytes"))
	return meter.get_day_row(
		bucket, utc_today(), used, included=bucket.included, as_of=frappe.utils.now_datetime()
	)
