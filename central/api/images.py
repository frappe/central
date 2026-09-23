import frappe

from central.errors import handle_resource_operation
from central.integrations import images


@frappe.whitelist(methods=["GET"])
def list_offerings(team: str, flow: str = "Server") -> list[dict]:
	return images.list_offerings(team, flow)


@frappe.whitelist(methods=["GET"])
@handle_resource_operation
def list_images(team: str, region: str, offering: str, flow: str = "Server", offset: int = 0) -> dict:
	return images.list_images(team, region, offering, flow, offset)


@frappe.whitelist(methods=["GET"])
@handle_resource_operation
def eligible_plans(
	team: str, region: str, offering: str = "", image_id: str = "", snapshot: str | None = None
) -> dict:
	return images.eligible_plans(team, region, offering, image_id, snapshot)
