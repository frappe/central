"""Hands a service's report secret to the hosts that sign their usage reports with it."""

from dataclasses import dataclass

import frappe
from frappe.query_builder import DocType
from frappe.query_builder.functions import Coalesce

from central.services.doctype.service.service import (
	AI_SERVICE,
	STORAGE_SERVICE,
	get_report_secret,
	get_secret_delivery_status,
)

# A secret that changes on every send means an operator is still rotating; a fresh job sends it later.
MAXIMUM_SENDS = 3


@dataclass
class Delivery:
	"""One send: the secret sent, the save it came from, and the reason the host refused it."""

	secret: str
	run: str | None
	error: str | None = None


def send_report_secret(service: str) -> None:
	"""Queue the secret of `service` to each host that reports its usage, once this save commits."""
	# Each job reads the secret itself, so it is never stored in the queue.
	for host, region in delivery_targets(service):
		if host == "Cargo":
			_enqueue("send_to_cargo", region=region)
		else:
			_enqueue("send_to_grove")


def delivery_targets(service: str) -> list[tuple[str, str | None]]:
	"""The hosts, with the Cargo region, that sign the reports of `service`."""
	if service == STORAGE_SERVICE:
		return [("Cargo", region) for region in registered_cargo_regions()]
	if service == AI_SERVICE:
		return [("Grove", None)]
	return []


def registered_cargo_regions() -> list[str]:
	"""The regions whose Cargo Central has configured."""
	return frappe.get_all("Region", filters={"cargo_status": "Registered"}, pluck="name", order_by="name")


def send_to_cargo(region: str) -> None:
	"""Give one region's Cargo the storage report secret, with the webhook secret it already has."""
	_send_until_current(STORAGE_SERVICE, lambda sent: _send_to_cargo_once(region, sent), region)


def send_to_grove() -> None:
	"""Give Grove the AI report secret."""
	from central.integrations.grove import GroveClient

	try:
		client = GroveClient.from_settings()
	except frappe.ValidationError as error:
		# AI Settings without control credentials; recorded like a refusal, so the job does not fail.
		problem = _log_failure(AI_SERVICE, "Grove is not set up", error, get_report_secret(AI_SERVICE))
		_record_delivery(AI_SERVICE, None, _get_secret_run(AI_SERVICE), problem)
		return
	_send_until_current(AI_SERVICE, lambda sent: _send_to_grove_once(client, sent))


def _send_until_current(service: str, send_once, region: str | None = None) -> None:
	"""Send the stored secret again while it changes during a send, so the host ends with the latest."""
	# Two rotations can deliver out of order. The job that sends last checks the stored secret again,
	# so an older secret never stays on the host.
	last, is_settled = _send_latest(send_once)
	if not is_settled:
		_see_latest_commits()
		if get_report_secret(service) != last.secret:
			_send_later(service, region)
			return
	if last:
		_record_delivery(service, region, last.run, last.error)


def _send_latest(send_once) -> tuple[Delivery | None, bool]:
	"""Send until the stored secret stops changing. Returns the last send and if the secret settled."""
	last = None
	for _attempt in range(MAXIMUM_SENDS):
		if last:
			_see_latest_commits()
		delivery = send_once(last.secret if last else None)
		if not delivery:
			return last, True
		last = delivery
		if delivery.error:
			return last, True
	return last, False


def _send_later(service: str, region: str | None) -> None:
	"""Queue one fresh send of the newest secret, after recording that this job gave up."""
	host = "Cargo" if service == STORAGE_SERVICE else "Grove"
	problem = f"The secret changed during each of {MAXIMUM_SENDS} sends; a new job sends the newest."
	frappe.log_error(
		title=f"Report secret not sent to {host}",
		message=problem,
		reference_doctype="Region" if region else None,
		reference_name=region,
	)
	# One id per host, so a queued or running resend is never queued twice and a resend that gives
	# up again cannot queue itself; a later save queues its own job.
	job = "send_to_cargo" if service == STORAGE_SERVICE else "send_to_grove"
	kwargs = {"region": region} if region else {}
	_enqueue(job, job_id=f"report-secret-{service}-{region or 'all'}", deduplicate=True, **kwargs)
	# The resend clears this when it delivers. If it also gives up, the operator saves the secret again.
	problem += " If this stays Failed, enter the secret again and save."
	_record_delivery(service, region, _get_secret_run(service), problem)


def _see_latest_commits() -> None:
	# Under repeatable read, a second read in one transaction returns the value of the first read.
	# The job has written nothing yet, so ending its transaction loses nothing and shows a new secret.
	frappe.db.rollback()


def _get_secret_run(service: str) -> str | None:
	"""The run of the secret stored now."""
	return frappe.db.get_value("Service", service, "secret_run")


def _send_to_cargo_once(region: str, sent: str | None) -> Delivery | None:
	"""Send the stored secret to one region's Cargo unless it was just sent."""
	# An older Cargo ignores report_secret without an error, so a send can succeed and change nothing.
	from central.integrations.cargo import CargoClient

	# Locked, so a registration writing a new webhook secret meanwhile cannot be undone by this send,
	# and two sends to one region read the report secret one after the other.
	instance = frappe.get_doc("Region", region, for_update=True)
	secret = get_report_secret(STORAGE_SERVICE)
	if not secret or secret == sent:
		return None
	run = _get_secret_run(STORAGE_SERVICE)
	webhook_secret = instance.get_password("cargo_webhook_secret", raise_exception=False)
	if not webhook_secret:
		# Configuring without it would clear the secret Cargo signs its webhooks with.
		problem = "The region has no Cargo webhook secret. Register the region's Cargo again."
		frappe.log_error(
			title="Report secret not sent to Cargo",
			message=problem,
			reference_doctype="Region",
			reference_name=region,
		)
		return Delivery(secret, run, problem)
	try:
		CargoClient(instance).configure_webhooks(webhook_secret, secret)
	except frappe.ValidationError as error:
		return Delivery(
			secret, run, _log_failure(STORAGE_SERVICE, "Cargo refused the secret", error, secret, region)
		)
	return Delivery(secret, run)


def _send_to_grove_once(client, sent: str | None) -> Delivery | None:
	"""Send the stored AI secret to Grove unless it was just sent."""
	secret = get_report_secret(AI_SERVICE)
	if not secret or secret == sent:
		return None
	run = _get_secret_run(AI_SERVICE)
	try:
		client.set_report_secret(secret)
	except frappe.ValidationError as error:
		return Delivery(secret, run, _log_failure(AI_SERVICE, "Grove refused the secret", error, secret))
	return Delivery(secret, run)


def _enqueue(job: str, **kwargs) -> None:
	frappe.enqueue(
		f"central.integrations.report_secret.{job}",
		queue="short",
		enqueue_after_commit=True,
		**kwargs,
	)


def _log_failure(
	service: str, problem: str, error: Exception, secret: str | None, region: str | None = None
) -> str:
	"""Log a failed send with the secret masked. Returns the readable reason for the delivery row."""
	# An explicit message, so the log holds no traceback whose frames could show the secret, and a
	# host that echoes the secret in its refusal does not put it in the log either.
	message = f"{type(error).__name__}: {error}"
	if secret:
		message = message.replace(secret, "***")
	host = "Cargo" if service == STORAGE_SERVICE else "Grove"
	frappe.log_error(
		title=f"Report secret not sent to {host}",
		message=message,
		reference_doctype="Region" if region else None,
		reference_name=region,
	)
	return f"{problem}. {message}"


def _record_delivery(service: str, region: str | None, run: str | None, error: str | None) -> None:
	"""Record one host's result on its row of `run` and update the Service's summary."""
	# The job ends its transaction to see a newer secret, so this runs only after its last send.
	# The job commits the result when it ends.
	row = DocType("Report Secret Delivery")
	# Locked, so two regions that end at once each see the other's row when they sum up.
	frappe.db.get_value("Service", service, "name", for_update=True)
	(
		frappe.qb.update(row)
		.set(row.status, "Failed" if error else "Delivered")
		.set(row.error, error)
		.set(row.updated_at, frappe.utils.now_datetime())
		.where(row.parenttype == "Service")
		.where(row.parent == service)
		.where(row.run == run)
		.where(Coalesce(row.region, "") == (region or ""))
	).run()
	# A locking read, as a plain read in this transaction can return rows older than another job's commit.
	statuses = (
		frappe.qb.from_(row)
		.select(row.status)
		.where(row.parenttype == "Service")
		.where(row.parent == service)
		.for_update()
	).run(pluck=True)
	# Not modified, so an operator with the form open can still save it.
	frappe.db.set_value(
		"Service",
		service,
		"secret_delivery_status",
		get_secret_delivery_status(statuses),
		update_modified=False,
	)
