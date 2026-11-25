"""Hands a service's report secret to the hosts that sign their usage reports with it."""

import frappe

from central.services.doctype.service.service import AI_SERVICE, STORAGE_SERVICE, get_report_secret

# A secret that changes on every send means an operator is still rotating; a fresh job sends it later.
MAXIMUM_SENDS = 3


def send_report_secret(service: str) -> None:
	"""Queue the secret of `service` to each host that reports its usage, once this save commits."""
	# Each job reads the secret itself, so it is never stored in the queue.
	if service == STORAGE_SERVICE:
		for region in registered_cargo_regions():
			_enqueue("send_to_cargo", region=region)
	elif service == AI_SERVICE:
		_enqueue("send_to_grove")


def registered_cargo_regions() -> list[str]:
	"""The regions whose Cargo Central has configured."""
	return frappe.get_all("Region", filters={"cargo_status": "Registered"}, pluck="name", order_by="name")


def send_to_cargo(region: str) -> None:
	"""Give one region's Cargo the storage report secret, with the webhook secret it already has."""
	_send_until_current(STORAGE_SERVICE, "Cargo", lambda sent: _send_to_cargo_once(region, sent), region)


def send_to_grove() -> None:
	"""Give Grove the AI report secret."""
	from central.integrations.grove import GroveClient

	try:
		client = GroveClient.from_settings()
	except frappe.ValidationError as error:
		# AI Settings without control credentials; logged like a refusal, so the job does not fail.
		_log_failure("Grove", error, get_report_secret(AI_SERVICE))
		return
	_send_until_current(AI_SERVICE, "Grove", lambda sent: _send_to_grove_once(client, sent))


def _send_until_current(service: str, host: str, send_once, region: str | None = None) -> None:
	"""Send the stored secret again while it changes during a send, so the host ends with the latest."""
	# Two rotations can deliver out of order. The job that sends last checks the stored secret again,
	# so an older secret never stays on the host.
	sent = None
	for _attempt in range(MAXIMUM_SENDS):
		if sent:
			_see_latest_commits()
		latest = send_once(sent)
		if not latest:
			return
		sent = latest
	_see_latest_commits()
	if get_report_secret(service) != sent:
		_send_later(service, host, region)


def _send_later(service: str, host: str, region: str | None) -> None:
	"""Queue one fresh send of the newest secret, after logging that this job gave up."""
	frappe.log_error(
		title=f"Report secret not sent to {host}",
		message=f"The secret changed during each of {MAXIMUM_SENDS} sends; a new job sends the newest.",
		reference_doctype="Region" if region else None,
		reference_name=region,
	)
	# One id per host, so a queued or running resend is never queued twice and a resend that gives
	# up again cannot queue itself; a later save queues its own job.
	job = "send_to_cargo" if service == STORAGE_SERVICE else "send_to_grove"
	kwargs = {"region": region} if region else {}
	_enqueue(job, job_id=f"report-secret-{service}-{region or 'all'}", deduplicate=True, **kwargs)


def _see_latest_commits() -> None:
	# Under repeatable read, a second read in one transaction returns the value of the first read.
	# The job has written nothing yet, so ending its transaction loses nothing and shows a new secret.
	frappe.db.rollback()


def _send_to_cargo_once(region: str, sent: str | None) -> str | None:
	"""Send the stored secret to one region's Cargo unless it was just sent. Returns the sent secret."""
	# An older Cargo ignores report_secret without an error, so a send can succeed and change nothing.
	from central.integrations.cargo import CargoClient

	# Locked, so a registration writing a new webhook secret meanwhile cannot be undone by this send,
	# and two sends to one region read the report secret one after the other.
	instance = frappe.get_doc("Region", region, for_update=True)
	secret = get_report_secret(STORAGE_SERVICE)
	if not secret or secret == sent:
		return None
	webhook_secret = instance.get_password("cargo_webhook_secret", raise_exception=False)
	if not webhook_secret:
		# Configuring without it would clear the secret Cargo signs its webhooks with.
		frappe.log_error(
			title="Report secret not sent to Cargo",
			message="The region has no Cargo webhook secret.",
			reference_doctype="Region",
			reference_name=region,
		)
		return None
	try:
		CargoClient(instance).configure_webhooks(webhook_secret, secret)
	except frappe.ValidationError as error:
		_log_failure("Cargo", error, secret, region)
		return None
	return secret


def _send_to_grove_once(client, sent: str | None) -> str | None:
	"""Send the stored AI secret to Grove unless it was just sent. Returns the sent secret."""
	secret = get_report_secret(AI_SERVICE)
	if not secret or secret == sent:
		return None
	try:
		client.set_report_secret(secret)
	except frappe.ValidationError as error:
		_log_failure("Grove", error, secret)
		return None
	return secret


def _enqueue(job: str, **kwargs) -> None:
	frappe.enqueue(
		f"central.integrations.report_secret.{job}",
		queue="short",
		enqueue_after_commit=True,
		**kwargs,
	)


def _log_failure(host: str, error: Exception, secret: str | None, region: str | None = None) -> None:
	# An explicit message, so the log holds no traceback whose frames could show the secret, and a
	# host that echoes the secret in its refusal does not put it in the log either.
	message = f"{type(error).__name__}: {error}"
	if secret:
		message = message.replace(secret, "***")
	frappe.log_error(
		title=f"Report secret not sent to {host}",
		message=message,
		reference_doctype="Region" if region else None,
		reference_name=region,
	)
