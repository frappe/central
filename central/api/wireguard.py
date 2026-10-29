import frappe
from frappe import _
from frappe.utils.translations import _lt

from central.errors import handle_resource_operation
from central.permissions import wireguard_device_has_permission
from central.utils.guards import require_capability

ACCESS_MESSAGE = _lt(
	"You can't manage WireGuard devices for this team. Ask a team admin to review your access."
)

DEVICE_FIELDS = (
	"name",
	"title",
	"region",
	"status",
	"added_by",
	"public_key",
	"address",
	"allowed_ips",
	"endpoint",
	"gateway_public_key",
	"creation",
)


@frappe.whitelist(methods=["GET"])
@require_capability("server:wireguard", ACCESS_MESSAGE)
def list_wireguard_devices(team: str) -> dict:
	"""Return the team's devices with the gateway regions and the servers a device could reach."""
	devices = frappe.get_list(
		"WireGuard Device",
		filters={"team": team},
		fields=list(DEVICE_FIELDS),
		order_by="creation desc",
		limit_page_length=0,
	)
	# Region is System Manager only so read the two public fields as the system
	regions = frappe.get_all(
		"Region",
		filters={"status": "Active", "has_wireguard_gateway": 1},
		fields=["name", "display_name"],
		order_by="region asc",
	)

	servers = frappe.get_list(
		"Virtual Machine",
		filters={
			"team": team,
			"region": ("in", [region.name for region in regions] or [""]),
			"status": ("!=", "Terminated"),
		},
		fields=["resource_id", "title", "region", "ipv6_address", "has_wireguard_access"],
		order_by="title asc",
		limit_page_length=0,
	)

	# customers cannot read User so read only the names of the device owners as the system
	owners = {
		user.name: user.full_name
		for user in frappe.get_all(
			"User",
			filters={"name": ("in", list({device.added_by for device in devices}))},
			fields=["name", "full_name"],
		)
	}

	for device in devices:
		device.added_by_name = owners.get(device.added_by) or device.added_by
		device.can_delete = wireguard_device_has_permission(frappe._dict(device, team=team), ptype="delete")

	return {"devices": devices, "regions": regions, "servers": servers}


@frappe.whitelist(methods=["POST"])
@require_capability("server:wireguard", ACCESS_MESSAGE)
@handle_resource_operation
def create_wireguard_device(team: str, region: str, title: str, public_key: str) -> dict:
	"""Register a device with the region's gateway and return its settings."""
	device = frappe.get_doc(
		{
			"doctype": "WireGuard Device",
			"team": team,
			"region": region,
			"title": title,
			"public_key": public_key,
		}
	).insert()

	return {field: device.get(field) for field in DEVICE_FIELDS}


@frappe.whitelist(methods=["POST"])
@require_capability("server:wireguard", ACCESS_MESSAGE)
@handle_resource_operation
def delete_wireguard_device(team: str, name: str) -> dict:
	"""Remove a device from its gateway. A gateway outage leaves it Removing until a retry works."""
	device = frappe.get_doc("WireGuard Device", name)
	if device.team != team:
		frappe.throw(_("This device does not belong to the team."), frappe.PermissionError)
	if not device.has_permission("delete"):
		frappe.throw(
			_("You can remove only your own devices. Ask a team admin to remove this one."),
			frappe.PermissionError,
		)

	return {"is_removed": device.remove()}
