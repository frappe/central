# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe

from central.billing.revenue.usage_ledger import utc_today, write_days
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
	regions = billed_buckets()
	for region, names in regions.items():
		pages = [names[start : start + PAGE_SIZE] for start in range(0, len(names), PAGE_SIZE)]
		RegionRead(run, region).start(len(pages))
		for page in pages:
			frappe.enqueue(
				"central.billing.revenue.storage_bridge.read_page",
				queue=billing_queue(),
				run=run,
				region=region,
				names=page,
			)
	return sum(len(names) for names in regions.values())


def read_page(run: str, region: str, names: list[str]) -> int:
	"""Read one page of a region's buckets and write their days."""
	meter = frappe.get_doc("Service", STORAGE_SERVICE).get_meter(STORAGE_METER)
	rows, failed = [], []
	for name in names:
		# One bucket's failure, of any kind, must not stop the page's other buckets.
		try:
			rows.append(_reading(name, meter))
		except Exception as error:
			failed.append(f"{name}: {error!r}")
	written = write_days(rows)
	RegionRead(run, region).finish_page(failed)
	return written


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
		self.errors = f"storage_read:{run}:{region}:errors"
		self.pages = frappe.cache.make_key(f"storage_read:{run}:{region}:pages")

	def start(self, pages: int) -> None:
		# nosemgrep: frappe-cache-breaks-multitenancy -- make_key adds the site prefix; decr needs a raw int.
		frappe.cache.set(self.pages, pages, ex=RUN_TTL_SECONDS)

	def finish_page(self, failed: list[str]) -> None:
		"""Count the page's failures; the region's last page logs them all once."""
		# Failures are pushed before the page counter drops, so the last page sees every one.
		for line in failed:
			frappe.cache.rpush(self.errors, line)
		if failed:
			frappe.cache.expire_key(self.errors, RUN_TTL_SECONDS)
		if frappe.cache.decr(self.pages) == 0:
			self._log_failures()

	def _log_failures(self) -> None:
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
			)
		frappe.cache.delete_value(self.errors)
		frappe.cache.delete(self.pages)


def _reading(name: str, meter) -> dict:
	bucket = frappe.get_doc("Team Service", name)
	used = frappe.utils.flt(bucket.get_usage().get("used_bytes"))
	return meter.get_day_row(bucket, utc_today(), used, as_of=frappe.utils.now_datetime())
