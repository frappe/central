import re
from urllib.parse import urlencode

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import cint
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from central.signups.affiliates.cookie import read_visit_cookie, write_visit_cookie
from central.signups.doctype.affiliate_visit.affiliate_visit import UTM_FIELDS, AffiliateVisit
from central.signups.doctype.product.product import FRAPPE_CLOUD_PRODUCT_KEY, get_enabled_product_key
from central.site_provisioning import first_touch

LINK_PATH = re.compile(r"r/([a-z0-9][a-z0-9-]{0,31})", re.IGNORECASE)
CLICKS_PER_HOUR = 60
# Crawlers and link previews open a shared link without a person behind it. Most name themselves
# "...bot", such as Googlebot. A lowercase letter must come first, so a phone brand like CUBOT
# does not match. Do not match an app whose in-app browser a person uses, such as Telegram.
BOT_USER_AGENT = re.compile(
	r"[a-z][Bb]ot\b|(?i:crawl|spider|slurp|preview|facebookexternalhit|whatsapp|embedly|curl|wget|python|headless)"
)


class AffiliateLinkPage(BaseRenderer):
	"""Serves /r/<slug>, a named link or an affiliate's main code: counts a person's click and sends
	them to signup."""

	def can_render(self) -> bool:
		return bool(LINK_PATH.fullmatch(self.path))

	def render(self) -> Response:
		if frappe.request.method not in ("GET", "HEAD"):
			return Response(status=405, headers={"Allow": "GET, HEAD"})

		slug = LINK_PATH.fullmatch(self.path).group(1).lower()
		link = frappe.db.get_value(
			"Affiliate Link",
			slug,
			["name", "affiliate", "product", "utm_source", "utm_campaign"],
			as_dict=True,
		)
		product = get_enabled_product_key(get_link_value(link, "product"))
		touch = first_touch(**{field: get_link_value(link, field) for field in UTM_FIELDS})
		utm = {field: touch[field] for field in UTM_FIELDS}

		if is_person_clicking() and (affiliate := get_clicked_affiliate(slug, link)):
			try:
				count_click(affiliate, link.name if link else None, product, utm)
			except frappe.RateLimitExceededError:
				# The visitor still reaches signup. The click just does not count.
				pass

		return Response(
			status=302, headers={"Location": get_signup_url(product, utm), "Cache-Control": "no-store"}
		)


@rate_limit(limit=lambda: CLICKS_PER_HOUR, seconds=60 * 60)
def count_click(affiliate: str, link: str | None, product: str | None, utm: dict) -> None:
	"""Record the click and keep its visit in the visitor's cookie."""
	if cint(frappe.db.get_single_value("Central Settings", "affiliate_cookie_days")) <= 0:
		# A cookie that expires at once can never lead to a referral.
		return

	key = product or FRAPPE_CLOUD_PRODUCT_KEY
	visits = read_visit_cookie()
	earlier = visits.pop(key, None)
	visits[key] = AffiliateVisit.record_click(affiliate, link, product, utm, earlier)
	write_visit_cookie(visits)
	# Frappe rolls back a GET request unless it is told to commit.
	frappe.local.flags.commit = True


def get_link_value(link: dict | None, field: str) -> str | None:
	"""A named link fixes its product, source and campaign. The query fills only what it leaves empty."""
	return (link or {}).get(field) or frappe.request.args.get(field)


def is_person_clicking() -> bool:
	user_agent = frappe.request.headers.get("User-Agent", "")
	return frappe.request.method == "GET" and bool(user_agent) and not BOT_USER_AGENT.search(user_agent)


def get_clicked_affiliate(slug: str, link: dict | None) -> str | None:
	"""The Active affiliate of the named link or main code, unless the visitor is that affiliate."""
	owner = {"name": link.affiliate} if link else {"affiliate_code": slug}
	affiliate = frappe.db.get_value(
		"Affiliate", {**owner, "status": "Active"}, ["name", "user"], as_dict=True
	)
	return affiliate.name if affiliate and affiliate.user != frappe.session.user else None


def get_signup_url(product: str | None, utm: dict) -> str:
	query = {key: value for key, value in {"product": product, **utm}.items() if value}
	return f"/dashboard/signup?{urlencode(query)}" if query else "/dashboard/signup"
