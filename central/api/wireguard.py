import frappe
from frappe import _

from central.iam import can_on_any_server

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


def require_access(team: str, capability: str) -> None:
	if not can_on_any_server(frappe.session.user, team, capability):
		frappe.throw(
			_("You cannot manage WireGuard devices for this team. Ask a team admin to review your access."),
			frappe.PermissionError,
		)


@frappe.whitelist(methods=["GET"])
def list_wireguard_devices(team: str) -> dict:
	"""Return the team's devices with the gateway regions and the servers a device could reach."""
	require_access(team, "server:view")
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

	return {"devices": devices, "regions": regions, "servers": servers}


@frappe.whitelist(methods=["POST"])
def create_wireguard_device(team: str, region: str, title: str, public_key: str) -> dict:
	"""Register a device with the region's gateway and return its settings."""
	require_access(team, "server:wireguard")
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
def delete_wireguard_device(team: str, name: str) -> dict:
	"""Remove a device from its gateway. A gateway outage leaves it Removing until a retry works."""
	require_access(team, "server:wireguard")
	device = frappe.get_doc("WireGuard Device", name)
	if device.team != team:
		frappe.throw(_("This device does not belong to the team."), frappe.PermissionError)

	return {"is_removed": device.remove()}
