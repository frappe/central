from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, now_datetime
from frappe.utils.background_jobs import get_queue, get_queue_list
from frappe.utils.file_lock import LockTimeoutError
from frappe.utils.synchronization import filelock

from central.integrations.datum import send_to_datum

REQUEST_COUNTS_KEY = "central:telemetry:request_counts"
OPEN_ACTION_STATUSES = ("Queued", "Dispatching", "Sent", "In Progress", "Uncertain")
FINISHED_ACTION_STATUSES = ("Succeeded", "Failed", "Timed Out")
# Only these groups of /api/method/central.api.<group> get their own label, so the label set stays small.
API_GROUPS = {"auth", "identity", "jwks", "oidc", "pilot", "servers", "signups", "sites", "sso", "teams"}


class CentralMetrics:
	"""The gauges that show whether Central does its work: customer requests, resource actions, payments,
	billing, domains, snapshots, emails and background jobs. Each is a count or an age, never a label per record."""

	def __init__(self) -> None:
		self.now = now_datetime()
		self.timestamp = self.now.replace(tzinfo=ZoneInfo(get_system_timezone())).astimezone(UTC).isoformat()
		self.samples: list[dict] = []
		self.request_counts: dict[str, int] = {}

	def collect(self) -> list[dict]:
		for add in (
			self.add_requests,
			self.add_resource_actions,
			self.add_payments,
			self.add_billing,
			self.add_site_domains,
			self.add_snapshots,
			self.add_emails,
			self.add_webhooks,
			self.add_jobs,
		):
			add()
		return self.samples

	def add(self, metric: str, value: float, **labels: str) -> None:
		self.samples.append({"metric": metric, "value": float(value), "ts": self.timestamp, "labels": labels})

	def get_age(self, value: datetime | str | None) -> float:
		return max((self.now - get_datetime(value)).total_seconds(), 0) if value else 0

	def get_oldest_age(
		self, doctype: str, filters: dict, field: str = "creation", newest: bool = False
	) -> float:
		"""The age of the oldest, or the newest, matching record. 0 when none matches."""
		values = frappe.get_all(
			doctype, filters=filters, pluck=field, order_by=f"{field} {'desc' if newest else 'asc'}", limit=1
		)
		return self.get_age(values[0]) if values else 0

	def add_requests(self) -> None:
		"""Requests since the last accepted push, by group and status class. Reading resets the counts, and a failed push puts them back."""
		self.request_counts = take_request_counts()
		for field, count in self.request_counts.items():
			group, status_class = field.split("|", 1)
			self.add("central_requests", count, group=group, status_class=status_class)

	def add_resource_actions(self) -> None:
		"""Open actions and the oldest open one, and actions that finished in the last hour, for each region and action."""
		open_actions = frappe.get_all(
			"Resource Action",
			filters={"status": ("in", OPEN_ACTION_STATUSES)},
			fields=["region", "resource_type", "action", "creation"],
		)
		oldest: dict[tuple, datetime] = {}
		for row in open_actions:
			key = (row.region or "none", row.resource_type, row.action)
			oldest[key] = min(oldest.get(key, row.creation), row.creation)
		for (region, resource_type, action), creation in oldest.items():
			labels = {"region": region, "resource_type": resource_type, "action": action}
			self.add("central_resource_action_oldest_open_seconds", self.get_age(creation), **labels)

		finished = frappe.get_all(
			"Resource Action",
			filters={
				"status": ("in", FINISHED_ACTION_STATUSES),
				"completed_at": (">", self.now - timedelta(hours=1)),
			},
			fields=["region", "resource_type", "action", "status"],
		)
		for (region, resource_type, action, status), count in Counter(
			(row.region or "none", row.resource_type, row.action, row.status) for row in finished
		).items():
			self.add(
				"central_resource_actions_finished_last_hour",
				count,
				region=region,
				resource_type=resource_type,
				action=action,
				status=status,
			)

	def add_payments(self) -> None:
		"""Payment attempts of the last hour, the age of the newest capture, and gateway webhooks not processed yet."""
		attempts = frappe.get_all(
			"Payment Attempt",
			filters={"initiated_at": (">", self.now - timedelta(hours=1))},
			fields=["gateway", "status"],
		)
		for (gateway, status), count in Counter((row.gateway, row.status) for row in attempts).items():
			self.add("central_payment_attempts_last_hour", count, gateway=gateway or "none", status=status)

		for gateway in frappe.get_all("Payment Gateway", filters={"is_enabled": 1}, pluck="name"):
			filters = {"gateway": gateway, "status": "Captured", "completed_at": ("is", "set")}
			age = self.get_oldest_age("Payment Attempt", filters, "completed_at", newest=True)
			if age:
				self.add("central_payment_last_capture_seconds", age, gateway=gateway)

		received = frappe.get_all(
			"Webhook Event", filters={"status": "Received"}, fields=["gateway", "creation"]
		)
		oldest: dict[str, datetime] = {}
		for row in received:
			gateway = row.gateway or "none"
			oldest[gateway] = min(oldest.get(gateway, row.creation), row.creation)
		for gateway, creation in oldest.items():
			unprocessed = sum(1 for row in received if (row.gateway or "none") == gateway)
			self.add("central_gateway_webhooks_unprocessed", unprocessed, gateway=gateway)
			self.add(
				"central_gateway_webhook_oldest_unprocessed_seconds", self.get_age(creation), gateway=gateway
			)

		failed = frappe.get_all(
			"Webhook Event",
			filters={"status": "Failed", "modified": (">", self.now - timedelta(hours=1))},
			pluck="gateway",
		)
		for gateway, count in Counter(failed).items():
			self.add("central_gateway_webhooks_failed_last_hour", count, gateway=gateway or "none")

	def add_billing(self) -> None:
		"""The age of the oldest billing run that has not completed, and invoices that failed to sync to accounting."""
		self.add(
			"central_billing_run_oldest_open_seconds",
			self.get_oldest_age(
				"Billing Run", {"status": ("!=", "Complete"), "started_at": ("is", "set")}, "started_at"
			),
		)
		self.add(
			"central_invoices_sync_failed", frappe.db.count("Invoice", {"erpnext_sync_status": "Failed"})
		)

	def add_site_domains(self) -> None:
		"""Proxy routes that failed in the last hour, and the oldest route that is still pending."""
		for route_type in ("Site", "Domain"):
			failed = frappe.db.count(
				"Site Domain",
				{
					"route_type": route_type,
					"status": "Failed",
					"modified": (">", self.now - timedelta(hours=1)),
				},
			)
			oldest = self.get_oldest_age("Site Domain", {"route_type": route_type, "status": "Pending"})
			self.add("central_site_domains_failed_last_hour", failed, route_type=route_type)
			self.add("central_site_domain_oldest_pending_seconds", oldest, route_type=route_type)

	def add_snapshots(self) -> None:
		"""Snapshots that failed in the last day, and the oldest one still pending."""
		failed = frappe.get_all(
			"VM Snapshot",
			filters={"status": "Failed", "modified": (">", self.now - timedelta(days=1))},
			pluck="snapshot_type",
		)
		for snapshot_type in ("Automatic", "Manual", "Terminate"):
			self.add(
				"central_vm_snapshots_failed_last_day",
				failed.count(snapshot_type),
				snapshot_type=snapshot_type,
			)
		self.add(
			"central_vm_snapshot_oldest_pending_seconds",
			self.get_oldest_age("VM Snapshot", {"status": "Pending"}),
		)

	def add_emails(self) -> None:
		"""Emails that failed in the last hour, and the oldest email still waiting to be sent."""
		errors = frappe.db.count(
			"Email Queue", {"status": "Error", "modified": (">", self.now - timedelta(hours=1))}
		)
		self.add("central_emails_failed_last_hour", errors)
		# An email can wait for its send_after on purpose, so it waits from the later of the two times.
		waiting = frappe.get_all(
			"Email Queue",
			filters={"status": "Not Sent"},
			or_filters=[["send_after", "is", "not set"], ["send_after", "<=", self.now]],
			fields=["creation", "send_after"],
			order_by="creation asc",
			limit=1,
		)
		oldest = max(waiting[0].creation, waiting[0].send_after or waiting[0].creation) if waiting else None
		self.add("central_email_oldest_unsent_seconds", self.get_age(oldest))

	def add_webhooks(self) -> None:
		"""Webhook deliveries of the last day by webhook and status. Failed ones retry, Exhausted ones gave up.
		The creation filter keeps the read on its index."""
		add_webhook_requests(self, self.now)

	def add_jobs(self) -> None:
		"""Queue backlogs, failed jobs, and how late each scheduled Central job is."""
		for queue_name in get_queue_list():
			queue = get_queue(queue_name)
			self.add("central_job_queue_length", queue.count, queue=queue_name)

		for name in frappe.get_all(
			"Scheduled Job Type", filters={"stopped": 0, "method": ("like", "central.%")}, pluck="name"
		):
			job = frappe.get_doc("Scheduled Job Type", name)
			late = (self.now - job.get_next_execution()).total_seconds() if job.last_execution else 0
			self.add("central_scheduled_job_late_seconds", max(late, 0), job=job.method)


def add_webhook_requests(metrics: CentralMetrics, now: datetime) -> None:
	rows = frappe.get_all(
		"Webhook Request Log",
		filters={"creation": (">", now - timedelta(days=1))},
		fields=["webhook", "status"],
	)
	for (webhook, status), count in Counter(
		(row.webhook or "none", row.status or "none") for row in rows
	).items():
		metrics.add("frappe_webhook_requests_last_day", count, webhook=webhook, status=status)


def count_request(request, response) -> None:
	"""An `after_request` hook that counts Central requests in Redis by group and status class. It stays cheap:
	one Redis increment. The minute job reads and resets the counts."""
	group = get_request_group(request.path)
	if group:
		status_class = f"{response.status_code // 100}xx" if response else "5xx"
		frappe.cache.hincrby(frappe.cache.make_key(REQUEST_COUNTS_KEY), f"{group}|{status_class}", 1)


def restore_request_counts(counts: dict[str, int]) -> None:
	"""Put counts back after a failed push, so the next minute sends them."""
	key = frappe.cache.make_key(REQUEST_COUNTS_KEY)
	for field, count in counts.items():
		frappe.cache.hincrby(key, field, count)


def take_request_counts() -> dict[str, int]:
	"""Read and delete the counts in one transaction, so no request is lost or counted twice."""
	key = frappe.cache.make_key(REQUEST_COUNTS_KEY)
	pipe = frappe.cache.pipeline()
	pipe.hgetall(key)
	pipe.delete(key)
	counts = pipe.execute()[0] or {}
	return {frappe.safe_decode(field): int(count) for field, count in counts.items()}


def get_request_group(path: str) -> str | None:
	"""The group of a Central API path. Static files and pages are not counted."""
	if path.startswith("/api/method/central.api."):
		group = path.removeprefix("/api/method/central.api.").split(".", 1)[0]
		return group if group in API_GROUPS else "other"
	if path.startswith("/api/v2/document/") or path.startswith("/api/resource/"):
		return "document"
	if path.startswith("/api/"):
		return "other"
	return None


def publish_metrics() -> None:
	"""Scheduled every minute. Does nothing until the site config names a telemetry region."""
	region = frappe.conf.get("telemetry_region")
	if not region:
		return

	try:
		with filelock("central:telemetry:metrics", timeout=0):
			metrics = CentralMetrics()
			try:
				metrics.collect()
			except Exception:
				# A gauge query that raises must not lose the request counts already taken.
				restore_request_counts(metrics.request_counts)
				raise
			if not send_to_datum(region, "/v1/ingest", {"samples": metrics.samples}):
				restore_request_counts(metrics.request_counts)
	except LockTimeoutError:
		return
