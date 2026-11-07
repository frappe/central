import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from http.cookies import SimpleCookie
from typing import Any

from central_cli import __version__
from central_cli.errors import CentralError

TIMEOUT_SECONDS = 60
SIGN_IN_HINT = "Sign in with `central auth login`."
SIGNED_OUT_ERRORS = ("AuthenticationError", "SessionExpired", "CSRFTokenError")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
	"""Never follow a redirect: urllib would send the credentials to the new host."""

	def redirect_request(self, req, fp, code, msg, headers, newurl):
		raise CentralError(f"Central redirected to {newurl}. Use that URL with --url if you trust it.")


OPENER = urllib.request.build_opener(RefuseRedirect)


@dataclass
class Response:
	status: int
	headers: Message
	body: bytes


class CentralClient:
	"""Calls Central's whitelisted methods as one signed-in user."""

	def __init__(
		self,
		url: str | None,
		*,
		session_id: str | None = None,
		csrf_token: str | None = None,
		api_key: str | None = None,
		api_secret: str | None = None,
		team: str | None = None,
	) -> None:
		self.url = validate_url(url) if url else None
		self.session_id = session_id
		self.csrf_token = csrf_token
		self.api_key = api_key
		self.api_secret = api_secret
		self.team = team

	@property
	def has_credentials(self) -> bool:
		return bool(self.session_id or (self.api_key and self.api_secret))

	def get(self, method: str, **params: Any) -> Any:
		return self.call("GET", method, params)

	def post(self, method: str, **params: Any) -> Any:
		return self.call("POST", method, params)

	def call(self, http_method: str, method: str, params: dict[str, Any], *, is_guest: bool = False) -> Any:
		"""Call `/api/method/<method>` and return its `message`. Parameters set to None are left out."""
		if not self.url:
			raise CentralError("Set the Central URL with `central auth login --url <url>` or $CENTRAL_URL.")
		if not is_guest and not self.has_credentials:
			raise CentralError(f"You are not signed in. {SIGN_IN_HINT}")

		params = {key: value for key, value in params.items() if value is not None}
		response = self.send(self.build_request(http_method, method, params, is_guest=is_guest))
		if response.status >= 400:
			raise CentralError(get_error_message(response))

		self.read_session_cookie(response.headers)
		try:
			return json.loads(response.body or b"{}").get("message")
		except (ValueError, AttributeError):
			raise CentralError(f"{self.url} did not answer like Central. Check the URL.")

	def build_request(
		self, http_method: str, method: str, params: dict[str, Any], *, is_guest: bool = False
	) -> urllib.request.Request:
		url = f"{self.url}/api/method/{method}"
		headers = {"Accept": "application/json", "User-Agent": f"central-cli/{__version__}"}
		data = None
		if http_method == "GET":
			if params:
				url += "?" + urllib.parse.urlencode(
					{key: encode_query_value(value) for key, value in params.items()}
				)
		else:
			headers["Content-Type"] = "application/json"
			data = json.dumps(params).encode()

		if not is_guest:
			headers.update(self.auth_headers)

		return urllib.request.Request(url, data=data, headers=headers, method=http_method)

	@property
	def auth_headers(self) -> dict[str, str]:
		"""An API key wins over a saved session, so automation never acts as the last person to sign in."""
		if self.api_key and self.api_secret:
			return {"Authorization": f"token {self.api_key}:{self.api_secret}"}

		headers = {"Cookie": f"sid={self.session_id}"}
		if self.csrf_token:
			headers["X-Frappe-CSRF-Token"] = self.csrf_token
		return headers

	def send(self, request: urllib.request.Request) -> Response:
		try:
			with OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
				return Response(response.status, response.headers, response.read())
		except urllib.error.HTTPError as error:
			return Response(error.code, error.headers, error.read())
		except urllib.error.URLError as error:
			raise CentralError(f"Could not reach {self.url}: {error.reason}")

	def read_session_cookie(self, headers: Message) -> None:
		"""Keep the session Central sets on sign-in. A guest session is not a sign-in."""
		for header in headers.get_all("Set-Cookie") or []:
			cookie = SimpleCookie()
			cookie.load(header)
			if "sid" in cookie and cookie["sid"].value not in ("", "Guest"):
				self.session_id = cookie["sid"].value

	def require_team(self) -> str:
		"""The chosen team, else the user's only team."""
		if self.team:
			return self.team

		teams = [team for team in self.get("central.api.identity.my_teams") if team.get("status") == "Active"]
		if len(teams) != 1:
			raise CentralError(
				f"You are in {len(teams)} active teams. Pick one with `central team use <team>` or --team."
			)

		self.team = teams[0]["name"]
		return self.team


def validate_url(url: str) -> str:
	"""Credentials travel only over HTTPS. Plain HTTP is for a local development site."""
	parts = urllib.parse.urlsplit(url.rstrip("/"))
	host = parts.hostname or ""
	is_local = host in LOCAL_HOSTS or host.endswith(".localhost")
	if parts.scheme == "https" or (parts.scheme == "http" and is_local):
		return url.rstrip("/")

	raise CentralError(f"Use an https:// URL for Central, not {url}.")


def encode_query_value(value: Any) -> str:
	if isinstance(value, bool):
		return "1" if value else "0"
	if isinstance(value, (dict, list)):
		return json.dumps(value)
	return str(value)


def get_error_message(response: Response) -> str:
	"""The messages Frappe queued for the user, else the exception, else the HTTP status."""
	try:
		data = json.loads(response.body)
	except ValueError:
		data = None
	if not isinstance(data, dict):
		return f"Central returned HTTP {response.status}."

	if is_signed_out(data):
		return f"Central did not accept your session or API key. {SIGN_IN_HINT}"

	messages = [strip_html(message) for message in read_server_messages(data.get("_server_messages"))]
	message = " ".join(message for message in messages if message)
	if not message:
		message = data.get("exception") or data.get("exc_type") or f"Central returned HTTP {response.status}."
	return message


def is_signed_out(data: dict) -> bool:
	"""Frappe treats an expired session as Guest, and refuses a Guest with a login message."""
	if data.get("exc_type") in SIGNED_OUT_ERRORS:
		return True
	return data.get("exc_type") == "PermissionError" and "Login to access" in (
		data.get("_server_messages") or ""
	)


def read_server_messages(raw: str | None) -> list[str]:
	if not raw:
		return []

	try:
		items = [json.loads(item) for item in json.loads(raw)]
	except (TypeError, ValueError):
		return [raw]

	return [item.get("message", "") if isinstance(item, dict) else str(item) for item in items]


def strip_html(text: str) -> str:
	return re.sub(r"<[^>]+>", "", text).strip()
