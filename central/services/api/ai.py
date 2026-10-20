import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.translations import _lt

from central.integrations.grove import GroveClient, GroveUnavailable
from central.services import ai
from central.utils.guards import require_capability

VIEW_DENIED = _lt("You can't view this team's AI. Ask a team admin to review your access.")
MANAGE_DENIED = _lt("You can't manage this team's AI. Ask a team admin to review your access.")
KEY_FIELDS = (
	"name",
	"title",
	"status",
	"creation",
	"revocable_at",
	"masked",
	"geography",
	"gateway_url",
	"cap",
	"month_spent",
	"limits",
)

# Grove owns the keys. Central keeps none: a secret is shown once, in the answer that mints it.


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_ai(team: str | None = None) -> dict:
	"""Whether AI is on for the team and, when it is, its spend and limits, this month's usage
	and the geographies a key may be minted in. `unavailable` while Grove is down or in
	maintenance: the page says so, and the keys keep working at the gateways."""
	if not ai.get_ai_service(team):
		return {"enabled": False}

	try:
		return {"enabled": True, **ai.get_overview(team)}
	except GroveUnavailable:
		return {"enabled": True, "unavailable": True}


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def enable_ai(team: str | None = None) -> dict:
	"""Turn AI on for the team. Safe to repeat."""
	return {"name": ai.enable(team)}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def list_api_keys(team: str | None = None) -> list[dict]:
	"""The team's keys, newest first, masked, each with its geography and the gateway it
	calls, its monthly cap, its spend this month, and its rate limits."""
	require_ai(team)
	keys = GroveClient.from_settings().get_figures(team)["keys"]
	return [{field: row.get(field) for field in KEY_FIELDS} for row in keys]


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def create_api_key(
	team: str | None = None, label: str | None = None, geography: str | None = None, cap: int | None = None
) -> dict:
	"""Mint a key for the team in `geography` (Grove's default when none) with `cap` whole USD
	to spend a month (none: the key is refused until it gets one), and return its secret.
	This is the only time it is shown. `models` is what it may call, for the quickstart."""
	require_ai(team)
	label = (label or "").strip()
	if not label:
		frappe.throw(_("Enter a name for the API key so you can identify it later."))

	client = GroveClient.from_settings()
	key = client.provision_key(
		team, label, geography or None, whole_dollars(cap) if cap is not None else None
	)
	return {
		"name": key["name"],
		"label": label,
		"geography": key["geography"],
		"gateway_url": key["gateway_url"],
		"api_key": key["api_key"],
		"models": key_models_or_none(team, key["name"]),
	}


def key_models_or_none(team: str, key: str) -> list[dict]:
	"""The models for the quickstart, or none: the secret is shown once, and a failed read of what
	the key may call must not cost it. The Grove client has logged the failure already."""
	try:
		return ai.get_key_models(team, key)
	except frappe.ValidationError:
		frappe.clear_last_message()
		return []


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def set_api_key_caps(team: str | None = None, caps: dict[str, int] | None = None) -> list[dict]:
	"""Set the monthly caps of several of the team's keys in one go, {key: whole USD}. Grove
	saves all or none: it refuses caps that add up past the tier's spend limit, and another
	team's key."""
	require_ai(team)
	rows = GroveClient.from_settings().update_caps(
		team, {key: whole_dollars(cap) for key, cap in (caps or {}).items()}
	)
	return [{field: row.get(field) for field in KEY_FIELDS} for row in rows]


def whole_dollars(cap: int | float | str) -> int:
	"""A monthly cap is whole US dollars. The console's inputs step by one; a fraction that
	still arrives is refused, not rounded. Grove takes the figure as given."""
	value = flt(cap)
	if value != int(value):
		frappe.throw(_("A cap is whole US dollars."))
	return int(value)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def set_prompt_logging(enabled: bool, team: str | None = None) -> dict:
	"""Whether the gateways store the prompts and outputs of the team's keys, for a short time,
	so support can look into a request. Grove holds the setting; Central keeps no copy."""
	require_ai(team)
	updated = GroveClient.from_settings().update_team(team, log_payloads=enabled)
	return {"log_payloads": bool(updated["log_payloads"])}


@frappe.whitelist(methods=["POST"])
@require_capability("service:view", VIEW_DENIED)
def pull_usage(team: str | None = None) -> dict:
	"""Ask Grove to pull the team's usage from its gateways now (the console's **Refresh usage**),
	so the spend, keys and usage reads that follow are of this moment. Grove allows 2 an hour per
	team."""
	require_ai(team)
	return GroveClient.from_settings().pull_usage(team)


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_models(team: str | None = None, geography: str | None = None) -> list[dict]:
	"""What a key in `geography` (Grove's default when none) starts with: its default group."""
	require_ai(team)
	return ai.get_models(geography or None)


@frappe.whitelist(methods=["POST"])
@require_capability("service:manage", MANAGE_DENIED)
def revoke_api_key(team: str | None = None, key: str | None = None) -> dict:
	"""Revoke one of the team's keys. Grove refuses another team's key."""
	require_ai(team)
	GroveClient.from_settings().revoke_key(team, key)

	return {"name": key}


@frappe.whitelist(methods=["GET"])
@require_capability("service:view", VIEW_DENIED)
def get_usage(team: str | None = None, period: str = "Last 7 Days", key: str | None = None) -> dict:
	"""What the team used over a period, or through one of its keys: requests and cost, in
	total, per model, and per day."""
	require_ai(team)
	return ai.get_usage_report(team, period, get_key_hash(team, key) if key else None)


def require_ai(team: str) -> None:
	if not ai.get_ai_service(team):
		frappe.throw(_("AI is not enabled for this team. Ask a team admin to enable it on the LLM page."))


def get_key_hash(team: str, key: str) -> str:
	"""The hash Grove narrows usage by, for one of the team's own keys."""
	for row in GroveClient.from_settings().get_figures(team)["keys"]:
		if row["name"] == key:
			return row["key_hash"]
	frappe.throw(
		_(
			"This API key is not available on this team. Refresh the API keys list and select a key from this team."
		),
		frappe.DoesNotExistError,
	)
