import base64
import hashlib
import json
import threading
import urllib.parse
import urllib.request

import httpx
import keyring
import pytest
import respx
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from fcloud.auth import loopback

URL = "https://central.test"


class MemoryKeyring(KeyringBackend):
	priority = 1

	def __init__(self):
		super().__init__()
		self.passwords = {}

	def get_password(self, service, username):
		return self.passwords.get((service, username))

	def set_password(self, service, username, password):
		self.passwords[(service, username)] = password

	def delete_password(self, service, username):
		if self.passwords.pop((service, username), None) is None:
			raise PasswordDeleteError(username)


class FakeCentral:
	"""Frappe's OAuth endpoints and the few API methods the CLI calls.

	respx builds responses with httpx types and serves them through the httpx2 transport the CLI uses.
	"""

	def __init__(self, router: respx.MockRouter):
		self.registrations = []
		self.revoked = []
		self.grants = []
		self.authorize_params = {}
		self.access_token = None
		self.refresh_token = None
		self.redirect_override = None

		metadata = {
			"authorization_endpoint": f"{URL}/authorize",
			"token_endpoint": f"{URL}/token",
			"revocation_endpoint": f"{URL}/revoke",
			"registration_endpoint": f"{URL}/register",
		}
		self.metadata = router.get(f"{URL}/.well-known/oauth-authorization-server").respond(json=metadata)
		router.post(f"{URL}/register").mock(side_effect=self.register)
		router.post(f"{URL}/token").mock(side_effect=self.token)
		router.post(f"{URL}/revoke").mock(side_effect=self.revoke)
		router.get(f"{URL}/api/method/frappe.auth.get_logged_user").mock(side_effect=self.get_logged_user)

	def register(self, request):
		self.registrations.append(json.loads(request.content))
		return httpx.Response(201, json={"client_id": f"client-{len(self.registrations)}"})

	def revoke(self, request):
		self.revoked.append(dict(urllib.parse.parse_qsl(request.content.decode())))
		return httpx.Response(200, json={})

	def token(self, request):
		form = dict(urllib.parse.parse_qsl(request.content.decode()))
		if form["grant_type"] == "authorization_code" and not self.is_valid_exchange(form):
			return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE mismatch"})
		if form["grant_type"] == "refresh_token" and form["refresh_token"] != self.refresh_token:
			return httpx.Response(
				400, json={"error": "invalid_grant", "error_description": "Invalid refresh token"}
			)

		self.grants.append(form["grant_type"])
		self.access_token, self.refresh_token = f"access-{len(self.grants)}", f"refresh-{len(self.grants)}"
		token = {"access_token": self.access_token, "refresh_token": self.refresh_token, "expires_in": 3600}
		return httpx.Response(200, json={**token, "token_type": "Bearer"})

	def is_valid_exchange(self, form: dict) -> bool:
		digest = hashlib.sha256(form["code_verifier"].encode()).digest()
		challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
		params = self.authorize_params
		return challenge == params["code_challenge"] and form["client_id"] == params["client_id"]

	def get_logged_user(self, request):
		if request.headers["Authorization"] in (f"Bearer {self.access_token}", "token key1:secret1"):
			return httpx.Response(200, json={"message": "user@example.com"})
		return httpx.Response(403, json={"exc_type": "PermissionError", "exception": "Not permitted"})

	def open_browser(self, authorize_url: str) -> bool:
		"""Approve the sign-in the way Central does: redirect to the CLI's loopback with a code."""
		self.authorize_params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(authorize_url).query))
		redirect = self.redirect_override or {"code": "code-1", "state": self.authorize_params["state"]}
		target = f"{self.authorize_params['redirect_uri']}?{urllib.parse.urlencode(redirect)}"
		threading.Thread(
			target=lambda: urllib.request.urlopen(target, timeout=10).read(), daemon=True
		).start()
		return True


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
	"""Keep every test off the real keyring, config file, and environment."""
	keyring.set_keyring(MemoryKeyring())
	monkeypatch.setenv("FCLOUD_CONFIG_DIR", str(tmp_path))
	for name in ("FCLOUD_URL", "FCLOUD_API_KEY", "FCLOUD_API_SECRET"):
		monkeypatch.delenv(name, raising=False)


@pytest.fixture
def central(httpx2_mock, monkeypatch) -> FakeCentral:
	fake = FakeCentral(httpx2_mock)
	monkeypatch.setattr(loopback.webbrowser, "open", fake.open_browser)
	return fake
