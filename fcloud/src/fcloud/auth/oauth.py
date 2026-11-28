import time
import urllib.parse
from dataclasses import dataclass

import httpx2
from authlib.common.errors import AuthlibBaseError
from authlib.common.security import generate_token
from authlib.integrations.httpx_client import OAuth2Client

from fcloud.auth.loopback import REDIRECT_URI, wait_for_redirect
from fcloud.errors import FcloudError, LoginError

# Frappe grants a token the same access as the user's session, whatever the scope.
SCOPE = "all"
TIMEOUT_SECONDS = 30


@dataclass
class OAuthTokens:
	access_token: str
	refresh_token: str
	expires_at: float

	@classmethod
	def from_response(cls, token: dict, refresh_token: str = "") -> "OAuthTokens":
		return cls(
			access_token=token["access_token"],
			# Keep the old refresh token when the server doesn't rotate it.
			refresh_token=token.get("refresh_token") or refresh_token,
			expires_at=float(token.get("expires_at") or time.time() + int(token.get("expires_in", 3600))),
		)


class AuthorizationServer:
	"""Central's OAuth 2.0 server: browser sign-in with an authorization code and PKCE, refresh, and revocation."""

	def __init__(self, url: str):
		require_secure_url(url)
		self.url = url
		self.metadata = self.get_metadata()

	def get_metadata(self) -> dict:
		"""The authorization server metadata (RFC 8414)."""
		response = httpx2.get(f"{self.url}/.well-known/oauth-authorization-server", timeout=TIMEOUT_SECONDS)
		if response.status_code == 404:
			raise FcloudError(f"{self.url} doesn't publish OAuth server metadata. Log in with --api-key.")
		response.raise_for_status()
		return response.json()

	def register_client(self) -> str:
		"""Register the CLI as a public client (RFC 7591), so there is no client secret to store."""
		if "registration_endpoint" not in self.metadata:
			raise FcloudError(f"{self.url} doesn't allow OAuth client registration. Log in with --api-key.")

		client = {
			"client_name": "fcloud",
			"redirect_uris": [REDIRECT_URI],
			"token_endpoint_auth_method": "none",
			"grant_types": ["authorization_code", "refresh_token"],
			"response_types": ["code"],
			"scope": SCOPE,
		}
		response = httpx2.post(self.metadata["registration_endpoint"], json=client, timeout=TIMEOUT_SECONDS)
		if response.is_error:
			raise LoginError(f"Client registration failed: {get_oauth_error(response)}")
		return response.json()["client_id"]

	def login(self, client_id: str) -> OAuthTokens:
		"""Sign in through the browser and return the tokens."""
		with get_client(client_id) as client:
			verifier = generate_token(48)
			authorize_url, state = client.create_authorization_url(
				self.metadata["authorization_endpoint"], code_verifier=verifier
			)
			redirect = wait_for_redirect(authorize_url)
			# Frappe's denial redirect carries no state, so check for an error before Authlib checks the state.
			if "error" in redirect:
				raise LoginError(f"Sign-in failed: {redirect.get('error_description') or redirect['error']}")
			try:
				token = client.fetch_token(
					self.metadata["token_endpoint"],
					authorization_response=f"{REDIRECT_URI}?{urllib.parse.urlencode(redirect)}",
					code_verifier=verifier,
					state=state,
				)
			except AuthlibBaseError as error:
				raise LoginError(f"Sign-in failed: {error.description or error.error}")
		return OAuthTokens.from_response(token)

	def refresh(self, client_id: str, tokens: OAuthTokens) -> OAuthTokens:
		with get_client(client_id) as client:
			try:
				token = client.refresh_token(
					self.metadata["token_endpoint"], refresh_token=tokens.refresh_token
				)
			except AuthlibBaseError as error:
				raise LoginError(
					f"Session expired ({error.description or error.error}). Run `fcloud auth login {self.url}`."
				)
		return OAuthTokens.from_response(token, tokens.refresh_token)

	def revoke(self, client_id: str, tokens: OAuthTokens) -> None:
		"""Revoking the refresh token also revokes its access token in Frappe."""
		with get_client(client_id) as client:
			response = client.revoke_token(
				self.metadata["revocation_endpoint"],
				token=tokens.refresh_token,
				token_type_hint="refresh_token",
			)
			response.raise_for_status()


def get_client(client_id: str) -> OAuth2Client:
	return OAuth2Client(
		client_id=client_id,
		token_endpoint_auth_method="none",
		scope=SCOPE,
		redirect_uri=REDIRECT_URI,
		code_challenge_method="S256",
		timeout=TIMEOUT_SECONDS,
	)


def require_secure_url(url: str) -> None:
	"""Bearer tokens must not travel in cleartext, except to a local development site."""
	host = urllib.parse.urlparse(url).hostname or ""
	is_local = host in ("localhost", "127.0.0.1") or host.endswith(".localhost")
	if url.startswith("http://") and not is_local:
		raise FcloudError("Use an https:// URL for OAuth. Plain http is for localhost only.")


def get_oauth_error(response: httpx2.Response) -> str:
	try:
		payload = response.json()
	except ValueError:
		payload = {}
	return payload.get("error_description") or payload.get("error") or f"HTTP {response.status_code}"
