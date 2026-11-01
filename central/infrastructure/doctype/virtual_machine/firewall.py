from __future__ import annotations

import json

from central.server_models import FirewallChange, FirewallRule

ANYWHERE = ["0.0.0.0/0", "::/0"]

# The region's private network. The web console, the regional proxy and the team's other
# servers reach a machine through it, and an enabled firewall filters it too.
PRIVATE_NETWORK = "fdaa::/16"

# Every new server starts with these rules. They are ordinary rules: the customer sees them
# and can remove them. IPv6 neighbour discovery and path MTU need ICMP.
DEFAULT_INBOUND_RULES = [
	FirewallRule(protocol="any", cidrs=[PRIVATE_NETWORK]),
	FirewallRule(protocol="icmp", cidrs=ANYWHERE),
]

# Central used to add this rule to every server and hide it, so every WireGuard VPN device
# passed the firewall. A device now needs a rule of its own.
LEGACY_DEVICE_RULE = {"protocol": "any", "ports": "", "cidrs": ["fdac::/16"]}

# Every new server gets these rules, so turning its firewall on later keeps SSH, HTTP
# and HTTPS open instead of blocking everything.
WEB_SERVER_FIREWALL = FirewallChange(
	enabled=True,
	inbound=[
		*DEFAULT_INBOUND_RULES,
		*(FirewallRule(protocol="tcp", ports=port, cidrs=ANYWHERE) for port in ("22", "80", "443")),
	],
	outbound=[FirewallRule(protocol="any", cidrs=ANYWHERE)],
)


def is_blocking_devices(is_enabled: bool, inbound: list[dict]) -> bool:
	"""True when an enabled firewall has no rule that lets a WireGuard VPN device in."""
	if not is_enabled:
		return False

	return not any(
		rule["protocol"] != "icmp"
		and any(cidr == "::/0" or cidr.startswith("fdac:") for cidr in rule["cidrs"])
		for rule in inbound
	)


def get_new_server_firewall(is_enabled: bool) -> dict:
	"""The Atlas firewall for a new server: the web server rules, on or off."""
	return get_atlas_firewall(WEB_SERVER_FIREWALL.model_copy(update={"enabled": is_enabled}))


def get_atlas_firewall(change: FirewallChange) -> dict:
	"""The firewall fields Atlas replaces. Atlas keeps the rules of a disabled firewall."""
	remote = {}
	if change.enabled is not None:
		remote["enabled"] = change.enabled
	if change.inbound is not None:
		remote["inbound"] = [rule.model_dump() for rule in change.inbound]
	if change.outbound is not None:
		remote["outbound"] = [rule.model_dump() for rule in change.outbound]

	return remote


def get_customer_rules(remote: dict) -> dict:
	"""Every rule of a firewall Atlas reports, in the form the console edits."""

	def normalize(rule: dict) -> dict:
		return {"protocol": rule["protocol"], "ports": rule.get("ports") or "", "cidrs": rule["cidrs"]}

	return {
		"inbound": [normalize(rule) for rule in remote.get("inbound") or []],
		"outbound": [normalize(rule) for rule in remote.get("outbound") or []],
	}


def get_observed_firewall(network: dict) -> dict:
	"""The Virtual Machine fields for the firewall Atlas reports in a VM's network."""
	remote = network.get("firewall") or {}

	return {
		"is_firewall_enabled": bool(remote.get("enabled")),
		"firewall_rules": json.dumps(get_customer_rules(remote), sort_keys=True),
	}
