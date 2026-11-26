import json
import time
from dataclasses import asdict
from typing import Protocol

from fcloud.auth.oauth import AuthorizationServer, OAuthTokens
from fcloud.profiles import Profile

REFRESH_MARGIN_SECONDS = 60


class Credential(Protocol):
	def get_authorization_header(self) -> str: ...

	def refresh(self) -> bool:
		"""Renew the credential after Central rejects it. False when it can't be renewed."""
		...


class ApiKeyCredential:
	def __init__(self, api_key: str, api_secret: str):
		self.api_key = api_key
		self.api_secret = api_secret

	@classmethod
	def from_secret(cls, secret: str) -> "ApiKeyCredential":
		api_key, _, api_secret = secret.partition(":")
		return cls(api_key, api_secret)

	def to_secret(self) -> str:
		return f"{self.api_key}:{self.api_secret}"

	def get_authorization_header(self) -> str:
		return f"token {self.api_key}:{self.api_secret}"

	def refresh(self) -> bool:
		return False


class OAuthCredential:
	"""OAuth tokens of a profile. Refreshes them before they expire and keeps the new ones in the keyring."""

	def __init__(self, profile: Profile, tokens: OAuthTokens):
		self.profile = profile
		self.tokens = tokens

	@classmethod
	def log_in(cls, name: str, url: str, client_id: str | None = None) -> "OAuthCredential":
		"""Sign in through the browser, registering a client first when there is none, and keep the tokens."""
		server = AuthorizationServer(url)
		profile = Profile(name, url, "oauth", client_id or server.register_client())
		credential = cls(profile, server.login(profile.client_id))
		profile.set_secret(cls.to_secret(credential.tokens))
		return credential

	@classmethod
	def from_profile(cls, profile: Profile) -> "OAuthCredential":
		return cls(profile, get_stored_tokens(profile))

	@staticmethod
	def to_secret(tokens: OAuthTokens) -> str:
		return json.dumps(asdict(tokens))

	@property
	def is_expiring(self) -> bool:
		return self.tokens.expires_at - REFRESH_MARGIN_SECONDS < time.time()

	def get_authorization_header(self) -> str:
		if self.is_expiring:
			self.refresh()
		return f"Bearer {self.tokens.access_token}"

	def refresh(self) -> bool:
		# Frappe revokes a token pair when it is refreshed. When another fcloud process refreshed first,
		# the pair this process holds is dead, so use the pair that process stored.
		stored = get_stored_tokens(self.profile)
		if stored.refresh_token != self.tokens.refresh_token:
			self.tokens = stored
			return True

		server = AuthorizationServer(self.profile.url)
		self.tokens = server.refresh(self.profile.client_id, self.tokens)
		self.profile.set_secret(self.to_secret(self.tokens))
		return True

	def revoke(self) -> None:
		AuthorizationServer(self.profile.url).revoke(self.profile.client_id, self.tokens)


def get_stored_tokens(profile: Profile) -> OAuthTokens:
	return OAuthTokens(**json.loads(profile.get_secret()))


def get_credential(profile: Profile) -> Credential:
	if profile.method == "oauth":
		return OAuthCredential.from_profile(profile)
	return ApiKeyCredential.from_secret(profile.get_secret())
