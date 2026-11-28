import frappe

from central.api.models.servers import ImageOffering, ImagePage, PlanCatalog, ReadyApp
from central.errors import handle_resource_operation
from central.integrations import images
from central.server_models import AppRequirements


@frappe.whitelist(methods=["GET"])
def list_offerings(team: str, flow: str = "Server") -> list[ImageOffering]:
	return images.list_offerings(team, flow)


@frappe.whitelist(methods=["GET"])
@handle_resource_operation
def list_images(team: str, region: str, offering: str, flow: str = "Server", offset: int = 0) -> ImagePage:
	return images.list_images(team, region, offering, flow, offset)


@frappe.whitelist(methods=["GET"])
@handle_resource_operation
def list_apps(team: str, region: str) -> list[ReadyApp]:
	return images.list_apps(team, region)


@frappe.whitelist(methods=["GET"])
@handle_resource_operation
def get_app_requirements(team: str, region: str, application: str) -> AppRequirements:
	return images.get_app_requirements(team, region, application)


@frappe.whitelist(methods=["GET"])
@handle_resource_operation
def eligible_plans(
	team: str, region: str, offering: str = "", image_id: str = "", snapshot: str | None = None
) -> PlanCatalog:
	return images.eligible_plans(team, region, offering, image_id, snapshot)
