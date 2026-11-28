import json
import re
from urllib.parse import unquote, urlencode, urlparse

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, cint, get_datetime, now, now_datetime
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from central.site_provisioning import first_touch

COOKIE_NAME = "central_affiliate"
LINK_PATH = re.compile(r"r/([a-z0-9]{1,32})", re.IGNORECASE)
CAMPAIGN_FIELDS = ("utm_source", "utm_medium", "utm_campaign")
# Frappe URL-encodes the cookie, which can triple a value. This keeps it under the 4 KB browser limit.
POST_URL_LENGTH = 500
CLICKS_PER_HOUR = 60
# Crawlers and link previews, such as Googlebot. "[a-z]bot" skips the phone brand CUBOT, and
# apps whose in-app browser a person uses, such as Telegram, are not matched.
BOT_USER_AGENT = re.compile(
	r"[a-z][Bb]ot\b|(?i:crawl|spider|slurp|preview|facebookexternalhit|whatsapp|embedly|curl|wget|python|headless)"
)


class AffiliateLinkPage(BaseRenderer):
	"""Serves /r/<code>: remembers the affiliate in a cookie and sends the visitor to signup."""

	def can_render(self) -> bool:
		return bool(LINK_PATH.fullmatch(self.path))

	def render(self) -> Response:
		if frappe.request.method not in ("GET", "HEAD"):
			return Response(status=405, headers={"Allow": "GET, HEAD"})

		code = LINK_PATH.fullmatch(self.path).group(1).lower()
		visit = get_visit(code)
		if is_person_clicking() and frappe.db.exists("Affiliate", {"code": code, "status": "Active"}):
			try:
				remember_visit(visit)
			except frappe.RateLimitExceededError:
				# The visitor still reaches signup. The click just does not count.
				pass

		return Response(
			status=302,
			headers={"Location": get_signup_url(visit["product"]), "Cache-Control": "no-store"},
		)


def get_visit(code: str) -> dict:
	"""What the link carried. Unknown parameters are ignored, and a bad value is dropped."""
	arguments = frappe.request.args
	product = arguments.get("product")
	touch = first_touch(**{field: arguments.get(field) for field in CAMPAIGN_FIELDS})

	return {
		"code": code,
		"product": get_enabled_product(product),
		**{field: touch[field] for field in CAMPAIGN_FIELDS},
		"utm_content": get_post_url(arguments.get("utm_content")),
		"clicked_on": now(),
	}


def get_enabled_product(value: str | None) -> str | None:
	"""The product a link names, when it is an enabled Product."""
	if isinstance(value, str) and value and frappe.db.exists("Product", {"name": value, "enabled": 1}):
		return value
	return None


def get_post_url(value: str | None) -> str | None:
	"""utm_content names the post that held the link, so only an http or https URL is kept."""
	if not isinstance(value, str):
		return None

	url = value.strip()[:POST_URL_LENGTH]
	try:
		parsed = urlparse(url)
	except ValueError:
		return None

	return url if parsed.scheme in ("http", "https") and parsed.netloc else None


def is_person_clicking() -> bool:
	user_agent = frappe.request.headers.get("User-Agent", "")
	return frappe.request.method == "GET" and bool(user_agent) and not BOT_USER_AGENT.search(user_agent)


@rate_limit(limit=CLICKS_PER_HOUR, seconds=60 * 60)
def remember_visit(visit: dict) -> None:
	"""Keep the visit in the browser. A newer click replaces an older one."""
	days = get_cookie_days()
	if days <= 0:
		return

	# Frappe URL-encodes the value when it sends the cookie.
	value = json.dumps(visit, separators=(",", ":"))
	frappe.local.cookie_manager.set_cookie(COOKIE_NAME, value, max_age=days * 24 * 60 * 60, httponly=True)


def get_signup_url(product: str | None) -> str:
	return f"/dashboard/signup?{urlencode({'product': product})}" if product else "/dashboard/signup"


def get_referral(user: str) -> dict:
	"""What a new team of `user` takes from the cookie: the affiliate, the link's product as the
	Landing Product, and its UTM values. A broken or expired cookie, a Paused affiliate, or the
	affiliate's own signup gives nothing."""
	visit = read_visit()
	code = visit.get("code")
	if not isinstance(code, str) or is_expired(visit.get("clicked_on")):
		return {}

	affiliate = frappe.db.get_value(
		"Affiliate", {"code": code.lower(), "status": "Active"}, ["name", "user"], as_dict=True
	)
	if not affiliate or affiliate.user == user:
		return {}

	# The browser can rewrite the cookie, so its values pass the same checks as the link.
	# All UTM values come from the click, even empty ones, so a team never mixes two visits.
	touch = first_touch(**{field: visit.get(field) for field in CAMPAIGN_FIELDS})
	return {
		"affiliate": affiliate.name,
		"landing_product": get_enabled_product(visit.get("product")),
		"utm_content": get_post_url(visit.get("utm_content")),
		**{field: touch[field] for field in CAMPAIGN_FIELDS},
	}


def read_visit() -> dict:
	request = getattr(frappe.local, "request", None)
	if not request:
		return {}

	try:
		visit = json.loads(unquote(request.cookies.get(COOKIE_NAME, "")))
	except ValueError:
		return {}

	return visit if isinstance(visit, dict) else {}


def is_expired(clicked_on: str | None) -> bool:
	"""The browser drops an expired cookie, but a shorter Cookie Days setting applies at once."""
	if not isinstance(clicked_on, str):
		return True

	try:
		clicked = get_datetime(clicked_on)
	except (ValueError, OverflowError):
		return True

	now = now_datetime()
	# A click in the future can only come from an edited cookie.
	return not add_days(now, -get_cookie_days()) <= clicked <= now


def forget_referral() -> None:
	"""A referral credits one team only. The cookie goes only once the team is committed, so a
	failed signup keeps it for the next try."""
	if cookie_manager := getattr(frappe.local, "cookie_manager", None):
		frappe.db.after_commit.add(lambda: cookie_manager.delete_cookie(COOKIE_NAME))


def get_cookie_days() -> int:
	return cint(frappe.db.get_single_value("Central Settings", "affiliate_cookie_days"))


def ensure_cookie_days() -> None:
	"""Seed Affiliate Cookie Days when it was never stored. A saved Single does not take a new
	field's default, and a fresh install skips patches. A stored value, even 0, is kept."""
	if "affiliate_cookie_days" in frappe.db.get_singles_dict("Central Settings"):
		return

	default = frappe.get_meta("Central Settings").get_field("affiliate_cookie_days").default
	frappe.db.set_single_value("Central Settings", "affiliate_cookie_days", cint(default))
