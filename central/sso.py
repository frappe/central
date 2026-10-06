from __future__ import annotations

import time

import frappe
import jwt
from frappe import _

from central.central.doctype.central_sso_settings.central_sso_settings import (
	ALGORITHM,
	CentralSSOSettings,
)

# Pilot ends an admin session when its login token expires, so this is the session length.
BENCH_LOGIN_TTL = 60 * 60
SITE_LOGIN_TTL = 5 * 60  # a single-use assertion that a site exchanges for its own session
BOOTSTRAP_TTL = 30 * 60  # the first-boot enrollment window
DATUM_TTL = 7 * 24 * 60 * 60  # short: no revocation list, and the pilot re-fetches on 401 / near expiry
ENROLL_SCOPE = "enroll"
DATUM_SCOPE = "datum"
DATUM_ACCESS = ["write"]  # datum serves no reads at all; every caller is a producer
ATLAS_TOKEN_TTL = 5 * 60


def mint_atlas_token(region_id: int) -> str:
	"""Mint an internal regional credential after the integration caller authorizes its operation."""
	return _mint_regional_token(region_id, f"atlas-admin:{region_id}", "*", {"tenant": "*"})


def mint_proxy_token(region_id: int) -> str:
	"""Mint a credential for the site and domain routes of one regional proxy."""
	return _mint_regional_token(region_id, f"atlas-proxy:{region_id}", "site:* domain:*")


def mint_cargo_token(region_id: int) -> str:
	"""Mint a credential for the object storage routes of one regional Cargo host."""
	return _mint_regional_token(region_id, f"atlas-cargo:{region_id}", "bucket:*")


def mint_datum_token(region_id: int, resource_id: str) -> str:
	"""The token a pilot presents to its region's datum, for metrics and logs alike. The
	audience names one region, so every other region refuses it."""
	if not resource_id:
		frappe.throw(
			_("This pilot has no resource yet; a datum token would be unattributable."),
			frappe.ValidationError,
		)

	return _mint_regional_token(
		region_id,
		f"atlas-datum:{region_id}",
		DATUM_SCOPE,
		{"resource_id": resource_id, "access": DATUM_ACCESS},
		ttl=DATUM_TTL,
	)


def _mint_regional_token(
	region_id: int, audience: str, scope: str, extra: dict | None = None, ttl: int = ATLAS_TOKEN_TTL
) -> str:
	if type(region_id) is not int or not 0 <= region_id <= 65535:
		frappe.throw(_("The Atlas region ID must be a whole number from 0 to 65535."))

	private_key, key_id = CentralSSOSettings.instance().get_signing_key("atlas")
	# JWT needs epoch seconds; Frappe helpers return naive datetimes or discard the time of day.
	now = int(time.time())
	claims = {
		"iss": "central",
		"sub": "central",
		"aud": audience,
		"scope": scope,
		"iat": now,
		"exp": now + ttl,
		"jti": frappe.generate_hash(length=16),
		**(extra or {}),
	}

	return jwt.encode(claims, private_key, algorithm=ALGORITHM, headers={"kid": key_id})


def central_url() -> str:
	"""Central's canonical base URL — the token issuer and JWKS host. Configured on
	Central SSO Settings; falls back to the site URL when unset."""
	return frappe.get_cached_doc("Central SSO Settings").issuer_url or frappe.utils.get_url()


def jwks_url() -> str:
	"""Where a bench fetches Central's public key(s) to verify minted tokens."""
	return f"{central_url()}/api/method/central.api.jwks.get_jwks"


def mint_bench_login(audience: str) -> str:
	"""A single-use admin SID that opens a bench. The bench verifies it against the JWKS
	and checks `aud` equals its own audience id."""
	return _mint(audience, "bench", BENCH_LOGIN_TTL, {"sub": "admin"})


def mint_site_login(audience: str, site: str, user: str | None = None, full_name: str | None = None) -> str:
	"""A one-time assertion the site's pilot exchanges for a session, scoped to one site. It
	signs `user` in, created on the site when missing, or Administrator when no user is
	named. `aud` is the hosting bench's audience id; the pilot verifies it against the JWKS."""
	claims = {"sub": user or "admin", "site": site}
	if user and full_name:
		claims["name"] = full_name
	return _mint(audience, "site", SITE_LOGIN_TTL, claims)


def mint_bootstrap_token(team: str, pilot_credential_id: str) -> str:
	"""A single-use enrollment token seeded into a VM at create time. The pilot presents it
	once to `central.api.pilot.enroll` to fetch its long-lived credential.

	`aud` is the `pilot_credential_id` — the per-deployment audience id. Central controls it
	up front (the VM's resource_id isn't known until Atlas provisions), so it doubles as the
	audience every downward token to this bench will carry."""
	return _mint(pilot_credential_id, ENROLL_SCOPE, BOOTSTRAP_TTL, {"team": team})


def verify_bootstrap_token(token: str) -> dict:
	"""Validate an enrollment token with Central's own public key and return the grant it
	carries: ``{team, pcid, jti}`` (pcid = the `aud`). Raises on a bad/expired/wrong-scope
	token."""
	public_key = CentralSSOSettings.instance().get_public_key("pilot")
	try:
		claims = jwt.decode(
			token,
			public_key,
			algorithms=[ALGORITHM],
			options={"verify_aud": False, "require": ["exp", "aud", "jti", "scope"]},
		)
	except jwt.InvalidTokenError as exc:
		frappe.throw(_("Invalid enrollment token: {0}").format(exc), frappe.AuthenticationError)
	if claims.get("scope") != ENROLL_SCOPE:
		frappe.throw(_("Not an enrollment token."), frappe.AuthenticationError)
	return {"team": claims["team"], "pcid": claims["aud"], "jti": claims["jti"]}


def _mint(audience: str, scope: str, ttl: int, extra: dict | None = None) -> str:
	"""Mint a signed assertion. `scope` is a required, first-class claim (not buried
	in `extra`) so every token declares its purpose and verifiers can assert it —
	bench-login, enroll, and metrics tokens all share this key, and the scope is what
	keeps one from being accepted as another."""
	private_pem, kid = CentralSSOSettings.instance().get_signing_key("pilot")
	now = int(time.time())
	payload = {
		"iss": central_url(),
		"aud": audience,
		"iat": now,
		"exp": now + ttl,
		"jti": frappe.generate_hash(length=16),
		"scope": scope,
		**(extra or {}),
	}
	return jwt.encode(payload, private_pem, algorithm=ALGORITHM, headers={"kid": kid})
