import frappe

from central.infrastructure import runway
from central.integrations import runway as regional


@frappe.whitelist(methods=["POST"])
def claim_pool(pool: str, owner_id: str) -> dict:
	return runway.claim_pool(pool, owner_id)


@frappe.whitelist(methods=["POST"])
def renew_pool(pool: str, owner_id: str, fence: int, last_error: str = "") -> dict:
	return runway.renew_pool(pool, owner_id, fence, last_error)


@frappe.whitelist(methods=["POST"])
def reserve_lease(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	return runway.reserve_lease(pool, owner_id, fence, lease_id)


@frappe.whitelist(methods=["POST"])
def update_lease(
	pool: str,
	owner_id: str,
	fence: int,
	lease_id: str,
	event: str,
	runner_id: int = 0,
	job_id: str = "",
	workflow_run_id: str = "",
	result: str = "",
	error: str = "",
	request_id: int = 0,
	repository: str = "",
	request_labels: str = "",
) -> dict:
	return runway.update_lease(
		pool, owner_id, fence, lease_id, event, runner_id, job_id, workflow_run_id, result, error,
		request_id, repository, request_labels,
	)


@frappe.whitelist(methods=["POST"])
def ensure_vm(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	return regional.ensure_vm(pool, owner_id, fence, lease_id)


@frappe.whitelist(methods=["POST"])
def request_delete(pool: str, owner_id: str, fence: int, lease_id: str) -> dict:
	return regional.request_delete(pool, owner_id, fence, lease_id)
