import frappe


def execute() -> None:
	"""Mark every setup that expired or was cancelled before this release as released.

	The hourly job retries a release that has no `setup_released_at`. These rows were
	released, or not, by the old code, so they must not all call the gateway at once.
	"""
	method = frappe.qb.DocType("Payment Method")
	(
		frappe.qb.update(method)
		.set(method.setup_released_at, method.modified)
		.where(method.status.isin(["Expired", "Cancelled"]))
		.where(method.validated_at.isnull())
		.where(method.setup_reference.notnull() & (method.setup_reference != ""))
		.where(method.setup_released_at.isnull())
	).run()
