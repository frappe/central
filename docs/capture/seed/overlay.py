import base64
import secrets
from pathlib import Path

import frappe
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from frappe.utils import add_days, add_to_date, now_datetime
from frappe.utils.password import update_password

from central.infrastructure.doctype.team_ssh_key.team_ssh_key import fingerprint

ASSETS = Path(__file__).resolve().parents[1] / "assets"
REGION = "bom"
DOMAIN = "frappe.cloud"
HERO_SLUG = "northwind"
PASSWORD = "docs@2026"

TEAM_NAME = "Contrail Coffee"
EMAIL_DOMAIN = "contrail.example"

# (first name, last name, team role, billing demo roster suffix it replaces)
PEOPLE = [
	("Zara", "Quill", "Owner", "owner"),
	("Kofi", "Brightwater", "Admin", "admin"),
	("Ines", "Marlowe", "Admin", "developer"),
	("Otis", "Penny", "Billing", "billing"),
	("Bea", "Lockhart", "Viewer", "viewer"),
	("Juniper", "Hale", "Developer", None),
	("Rafa", "Ozturk", "Developer", None),
	("Nova", "Achebe", "Developer", None),
	("Teddy", "Zhou", "Viewer", None),
]
INVITEE = "ziggy"

# One row per billing-demo server, in creation order: (title, image offering, site subdomain or None).
FLEET = [
	("website", "pilot", "www-contrail"),
	("erp-staging", "pilot", "erp-staging"),
	("ci-runner", "ubuntu", None),
	("helpdesk", "pilot", "support"),
	("raven-chat", "pilot", "chat"),
	("erp-production", "pilot", "erp"),
	("hr-portal", "pilot", "hr"),
	("analytics", "ubuntu", None),
	("learning", "pilot", "learn"),
	("crm", "pilot", "crm"),
	("reporting-db", "ubuntu", None),
	("upgrade-test", "pilot", None),
]

SSH_KEYS = ["Zara's MacBook", "Kofi's ThinkPad", "CI deploy key"]

FIREWALL_RULES = {
	"inbound": [
		{"protocol": "tcp", "ports": "22", "cidrs": ["198.51.100.0/24"]},
		{"protocol": "tcp", "ports": "80", "cidrs": ["0.0.0.0/0", "::/0"]},
		{"protocol": "tcp", "ports": "443", "cidrs": ["0.0.0.0/0", "::/0"]},
	],
	"outbound": [{"protocol": "all", "ports": "", "cidrs": ["0.0.0.0/0", "::/0"]}],
}


def seed() -> dict:
	"""Turn the billing demo's first team into the documented Contrail Coffee team."""
	_region()
	_settings()
	team = frappe.get_value("Team", {"team_name": ["in", [HERO_SLUG, TEAM_NAME]]}, "name")
	owner = _people(team)
	_team(team)
	keys = _ssh_keys(team)
	servers = _servers(team, keys)
	_sites(team, servers)
	_snapshots(team, servers, owner)
	_invitations(team, owner)
	return {"team": team, "sign_in": owner, "password": PASSWORD, "servers": len(servers)}


def _region() -> None:
	region = frappe.get_doc("Region", REGION)
	region.update(
		{
			"display_name": "Mumbai, India",
			"provider": "Frappe",
			"country_code": "IN",
			"latitude": 19.0896,
			"longitude": 72.8656,
			"status": "Active",
			"proxy_domain": f"{REGION}.{DOMAIN}",
		}
	)
	region.save(ignore_permissions=True)

	# The demo region has no live Atlas, so record a healthy connection check.
	region.db_set({"reachable": 1, "connection_checked_at": now_datetime(), "last_synced_at": now_datetime()})


def _settings() -> None:
	settings = frappe.get_single("Central Settings")
	settings.update(
		{
			"wildcard_domain": DOMAIN,
			"enable_firewall": 1,
			"enable_public_ipv4": 1,
			"enable_public_ipv6": 1,
		}
	)
	settings.save(ignore_permissions=True)


def _people(team: str) -> str:
	"""Give the roster named people with avatars, and add the rest of the team. Return the owner's email."""
	for first_name, last_name, _role, roster_suffix in PEOPLE:
		email = f"{first_name.lower()}@{EMAIL_DOMAIN}"
		roster_email = f"{roster_suffix}-{HERO_SLUG}@example.com"
		if roster_suffix and frappe.db.exists("User", roster_email):
			frappe.rename_doc(
				"User", roster_email, email, merge=bool(frappe.db.exists("User", email)), force=True
			)
		_person(email, first_name, last_name)

	document = frappe.get_doc("Team", team)
	members = {row.user: row for row in document.members}
	for first_name, _last_name, role, _roster_suffix in PEOPLE:
		email = f"{first_name.lower()}@{EMAIL_DOMAIN}"
		if email in members:
			members[email].role = role
		else:
			document.append("members", {"user": email, "role": role, "status": "Active"})
	document.save(ignore_permissions=True)

	owner = f"{PEOPLE[0][0].lower()}@{EMAIL_DOMAIN}"
	update_password(owner, PASSWORD)
	return owner


def _person(email: str, first_name: str, last_name: str) -> None:
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.new_doc("User")
		user.update({"email": email, "first_name": first_name, "send_welcome_email": 0})
		user.insert(ignore_permissions=True)

	# A rename keeps the old `email` value, and sign-in looks the user up by it.
	user.update(
		{
			"email": email,
			"first_name": first_name,
			"last_name": last_name,
			"enabled": 1,
			"user_image": _attach(f"{first_name.lower()}.png", "User", email, "user_image"),
		}
	)
	user.flags.ignore_password_policy = True
	user.save(ignore_permissions=True)


def _team(team: str) -> None:
	document = frappe.get_doc("Team", team)
	document.team_name = TEAM_NAME
	document.team_logo = _attach("contrail.png", "Team", team, "team_logo")
	for row in document.onboarding_steps:
		row.status = "Skipped"
	document.save(ignore_permissions=True)

	# A save would sync the customer to the billing system, which the demo site does not run.
	frappe.db.set_value(
		"Billing Profile",
		team,
		{"legal_name": f"{TEAM_NAME} LLC", "email": f"billing@{EMAIL_DOMAIN}"},
		update_modified=False,
	)


def _attach(file_name: str, doctype: str, name: str, field: str) -> str:
	existing = frappe.db.get_value("File", {"file_name": file_name, "attached_to_name": name}, "file_url")
	if existing:
		return existing

	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": doctype,
			"attached_to_name": name,
			"attached_to_field": field,
			"is_private": 0,
			"content": (ASSETS / file_name).read_bytes(),
		}
	).insert(ignore_permissions=True)
	return file.file_url


def _ssh_keys(team: str) -> list[str]:
	"""Insert keys without their sync job, which would call the region."""
	frappe.db.delete("Team SSH Key", {"team": team})
	names = []
	for title in SSH_KEYS:
		public_key = _new_public_key(title)
		document = frappe.get_doc(
			{
				"doctype": "Team SSH Key",
				"title": title,
				"team": team,
				"public_key": public_key,
				"fingerprint": fingerprint(public_key),
			}
		)
		document.db_insert()
		names.append(document.name)
	return names


def _new_public_key(comment: str) -> str:
	key = ed25519.Ed25519PrivateKey.generate().public_key()
	raw = key.public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
	return f"{raw} {comment.lower().replace(' ', '-').replace(chr(39), '')}"


def _servers(team: str, keys: list[str]) -> list[dict]:
	"""Write observed state directly. A save would open IPv4 subscriptions and queue region calls."""
	names = frappe.get_all("Virtual Machine", {"team": team}, pluck="name", order_by="creation asc")
	servers = []
	for index, (name, (title, image, subdomain)) in enumerate(zip(names, FLEET, strict=True), start=1):
		is_pilot = image == "pilot"
		values = {
			"title": title,
			"image_offering": image,
			"has_site": int(bool(subdomain)),
			"frappe_version": "16" if is_pilot else None,
			"ipv6_address": f"fdac:4a:{index:x}::10",
			"has_public_ipv6": 1,
			"public_ipv6": f"2001:db8:4a:{index:x}::10",
			"public_ipv4": "203.0.113.24" if title == "erp-production" else None,
			"has_ipv4_internet": 1,
			"is_firewall_enabled": int(title in ("erp-production", "erp-staging")),
			"firewall_rules": frappe.as_json(FIREWALL_RULES),
			"is_termination_protected": int(title == "erp-production"),
			"gateway_url": f"https://admin-vm-{index:05d}.{REGION}.{DOMAIN}" if is_pilot else None,
			"atlas_vm_id": f"vm-{index:05d}",
			"atlas_host_id": "host-bom-1",
			"state_observed_at": now_datetime(),
			"last_reported_at": now_datetime(),
		}
		frappe.db.set_value("Virtual Machine", name, values, update_modified=False)
		_server_keys(name, keys if index <= 3 else keys[:1])
		servers.append({"name": name, "title": title, "subdomain": subdomain})

	_rename_in_notifications(team, servers)
	return servers


def _rename_in_notifications(team: str, servers: list[dict]) -> None:
	"""The billing demo wrote notifications with its own server names, such as `northwind-12`."""
	for notification in frappe.get_all("Team Notification", {"team": team}, ["name", "title", "message"]):
		values = {key: notification[key] or "" for key in ("title", "message")}
		# Replace the longest names first, so `northwind-1` does not match inside `northwind-12`.
		for index in range(len(servers), 0, -1):
			for key in values:
				values[key] = values[key].replace(f"{HERO_SLUG}-{index}", servers[index - 1]["title"])
		frappe.db.set_value("Team Notification", notification.name, values, update_modified=False)


def _server_keys(server: str, keys: list[str]) -> None:
	frappe.db.delete("Server SSH Key", {"parent": server})
	for index, key in enumerate(keys, start=1):
		frappe.get_doc(
			{
				"doctype": "Server SSH Key",
				"parent": server,
				"parenttype": "Virtual Machine",
				"parentfield": "ssh_keys",
				"idx": index,
				"team_ssh_key": key,
			}
		).db_insert()


def _sites(team: str, servers: list[dict]) -> None:
	"""Insert sites and domains without routing them, which would call the region proxy."""
	frappe.db.delete("Site Domain", {"team": team})
	frappe.db.delete("Site", {"team": team})
	for server in servers:
		if not server["subdomain"]:
			continue

		site_name = f"{server['subdomain']}.{REGION}.{DOMAIN}"
		frappe.get_doc(
			{
				"doctype": "Site",
				"site_name": site_name,
				"subdomain": server["subdomain"],
				"team": team,
				"server": server["name"],
				"ready_at": add_days(now_datetime(), -40),
				"claimed_at": add_days(now_datetime(), -40),
			}
		).db_insert()

		if server["title"] == "erp-production":
			_domain(f"erp.{EMAIL_DOMAIN}", team, server["name"], site_name)


def _domain(domain: str, team: str, server: str, site: str) -> None:
	frappe.get_doc(
		{
			"doctype": "Site Domain",
			"domain": domain,
			"route_type": "Domain",
			"team": team,
			"status": "Active",
			"region": REGION,
			"server": server,
			"site": site,
		}
	).db_insert()


def _snapshots(team: str, servers: list[dict], owner: str) -> None:
	"""Insert snapshots without sending them to the region."""
	frappe.db.delete("VM Snapshot", {"team": team})
	by_title = {server["title"]: server["name"] for server in servers}
	rows = [
		("erp-production", "Automatic", -6, 18_420),
		("erp-production", "Automatic", -30, 18_310),
		("erp-production", "Manual", -140, 17_950),
		("helpdesk", "Automatic", -7, 9_240),
		("crm", "Manual", -290, 7_610),
		("analytics", "Manual", -75, 6_120),
	]
	images = {title: image for title, image, _subdomain in FLEET}
	# Every snapshot is billed, and a billed snapshot has a subscription. Any team subscription stands in.
	subscription = frappe.db.get_value("Subscription", {"team": team}, "name")
	for title, snapshot_type, hours, size_mib in rows:
		created = add_to_date(now_datetime(), hours=hours)
		manual_labels = {
			"erp-production": "before-v16-upgrade",
			"crm": "before-data-import",
			"analytics": "clean-install",
		}
		label = manual_labels[title] if snapshot_type == "Manual" else created.strftime("%Y-%m-%d")
		document = frappe.get_doc(
			{
				"doctype": "VM Snapshot",
				"title": f"{title} · {label}",
				"team": team,
				"server": by_title[title],
				"region": REGION,
				"status": "Available",
				"snapshot_type": snapshot_type,
				"size_mib": size_mib,
				"is_free": 0,
				"subscription": subscription,
				# The console restores only Ubuntu snapshots.
				"is_restorable": int(images[title] == "ubuntu"),
				"image_offering": images[title],
				"requested_by": owner if snapshot_type == "Manual" else None,
				"expires_at": add_days(created, 2) if snapshot_type == "Automatic" else None,
				"atlas_image_id": f"img-{secrets.token_hex(4)}",
				"creation": created,
				"modified": created,
			}
		)
		document.db_insert()


def _invitations(team: str, owner: str) -> None:
	frappe.db.delete("Team Invitation", {"team": team})
	frappe.get_doc(
		{
			"doctype": "Team Invitation",
			"team": team,
			"email": f"{INVITEE}@{EMAIL_DOMAIN}",
			"role": "Developer",
			"resource_type": "*",
			"status": "Pending",
			"invited_by": owner,
			"expires_on": add_days(now_datetime(), 6),
			"token": base64.urlsafe_b64encode(secrets.token_bytes(24)).decode(),
			"creation": add_to_date(now_datetime(), hours=-20),
		}
	).db_insert()
