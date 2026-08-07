# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt
"""The self-serve Site one-click login-URL freshness policy.

Extracted from `api/sites.py` so the endpoints there stay thin: this owns how a
usable login URL is obtained — prefer a Central-signed assertion the site's own
pilot exchanges (no Atlas hop), else the stored URL if still fresh, else an
Atlas-regenerated one — and the 24h-session expiry handling that goes with it.
"""

from __future__ import annotations

import frappe

from central.integrations.atlas import AtlasClient
from central.integrations.pilot import fetch_site_login_url


def site_login_url(doc) -> str | None:
	"""Prefer a Central-signed assertion the site's own pilot exchanges (no Atlas hop);
	fall back to Atlas's regenerated URL when the pilot isn't enrolled or reachable yet."""
	return _pilot_site_login_url(doc) or _fresh_site_login_url(doc)


def _pilot_site_login_url(doc) -> str | None:
	"""Relay a Central-signed assertion to the site's own pilot, which returns a desk URL with a
	fresh local session. Resolves the hosting bench's audience + gateway from the credential
	Central bound at create_site; None (→ Atlas fallback) until the pilot enrolled and its VM is
	Running."""
	if not doc.pilot_credential_id:
		return None
	credential = frappe.qb.DocType("Pilot Credential")
	asset = frappe.qb.DocType("Asset")
	row = (
		frappe.qb.from_(credential)
		.inner_join(asset)
		.on(credential.asset == asset.name)
		.select(credential.audience_id, asset.gateway_url, asset.status)
		.where((credential.name == doc.pilot_credential_id) & (credential.status == "Active"))
	).run(as_dict=True)
	if not row or row[0].status != "Running":
		return None
	gateway = (row[0].gateway_url or "").rstrip("/")
	if not gateway:
		return None
	return fetch_site_login_url(gateway, row[0].audience_id, doc.name)


def _fresh_site_login_url(doc) -> str | None:
	"""The site's usable one-click login URL: the stored one if it hasn't expired,
	else a freshly-regenerated one. The URL is a short-lived (24h) session, so a
	tenant who lands on a stale mirror row would otherwise get a dead link — we
	re-mint on read instead. Best-effort: if the regenerate call fails (Atlas
	unreachable), fall back to the stored URL rather than blocking the handoff."""
	if doc.login_url and not _login_url_expired(doc.login_url_expires_at):
		return doc.login_url
	try:
		return _regenerate_site_login(doc.name, doc.cluster).get("login_url") or doc.login_url
	except Exception:
		frappe.log_error(title=f"Regenerate login failed for site {doc.name}")
		return doc.login_url or None


def _login_url_expired(expires_at) -> bool:
	"""True if a stored login URL is at/past its expiry (or carries no expiry — treat
	an unstamped URL as unusable and force a regenerate). A small skew guard trims the
	tail so we don't hand out a URL that dies mid-click."""
	if not expires_at:
		return True
	skew = frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=30)
	return frappe.utils.get_datetime(expires_at) <= skew


def _regenerate_site_login(name: str, cluster: str) -> dict:
	"""Ask Atlas to re-mint the site's login URL, re-mirror the fresh handoff, and
	return it. The Atlas Site controller re-signs the session in the guest and returns
	the Site-mirror shape; we upsert it so the stored URL + expiry stay in lockstep."""
	from central.central.doctype.site.site import Site

	instance = frappe.get_doc("Atlas Instance", cluster)
	fresh = AtlasClient(instance).regenerate_site_login(name)
	Site.mirror_site(cluster, fresh, synced_at=frappe.utils.now_datetime())
	return fresh
