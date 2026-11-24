"""Hands a service's report secret to the hosts that sign their usage reports with it."""

import frappe

from central.services.doctype.service.service import AI_SERVICE, STORAGE_SERVICE, get_report_secret


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
	# An older Cargo ignores report_secret without an error, so a send can succeed and change nothing.
	from central.integrations.cargo import CargoClient

	secret = get_report_secret(STORAGE_SERVICE)
	if not secret:
		return
	# Locked, so a registration writing a new webhook secret meanwhile cannot be undone by this send.
	instance = frappe.get_doc("Region", region, for_update=True)
	webhook_secret = instance.get_password("cargo_webhook_secret", raise_exception=False)
	if not webhook_secret:
		# Configuring without it would clear the secret Cargo signs its webhooks with.
		frappe.log_error(
			title="Report secret not sent to Cargo",
			message="The region has no Cargo webhook secret.",
			reference_doctype="Region",
			reference_name=region,
		)
		return
	try:
		CargoClient(instance).configure_webhooks(webhook_secret, secret)
	except frappe.ValidationError as error:
		_log_failure("Cargo", error, secret, region)


def send_to_grove() -> None:
	"""Give Grove the AI report secret."""
	from central.integrations.grove import GroveClient

	secret = get_report_secret(AI_SERVICE)
	if not secret:
		return
	try:
		GroveClient.from_settings().set_report_secret(secret)
	except frappe.ValidationError as error:
		_log_failure("Grove", error, secret)


def _enqueue(job: str, **kwargs) -> None:
	frappe.enqueue(
		f"central.integrations.report_secret.{job}",
		queue="short",
		enqueue_after_commit=True,
		**kwargs,
	)


def _log_failure(host: str, error: Exception, secret: str, region: str | None = None) -> None:
	# An explicit message, so the log holds no traceback whose frames could show the secret, and a
	# host that echoes the secret in its refusal does not put it in the log either.
	message = f"{type(error).__name__}: {error}".replace(secret, "***")
	frappe.log_error(
		title=f"Report secret not sent to {host}",
		message=message,
		reference_doctype="Region" if region else None,
		reference_name=region,
	)
