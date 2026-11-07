import json
import re
import threading
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from frappe_cloud.client import CentralClient, Response, get_error_message, validate_url
from frappe_cloud.errors import CentralError
from tests.conftest import FakeCentral, read_params


def make_client(routes: dict, **kwargs) -> FakeCentral:
	kwargs.setdefault("session_id", "session")
	return FakeCentral("https://central.test/", routes=routes, requests=[], **kwargs)


def error_response(status: int, body: dict | str) -> Response:
	return Response(status, Message(), (body if isinstance(body, str) else json.dumps(body)).encode())


def test_api_key_wins_over_session() -> None:
	client = CentralClient("https://central.test", session_id="sid", api_key="key", api_secret="secret")

	assert client.auth_headers == {"Authorization": "token key:secret"}


def test_session_sends_cookie_and_csrf_token() -> None:
	client = CentralClient("https://central.test", session_id="sid", csrf_token="csrf")

	assert client.auth_headers == {"Cookie": "sid=sid", "X-Frappe-CSRF-Token": "csrf"}


@pytest.mark.parametrize(
	"url", ["https://central.test/", "http://localhost:8000", "http://central.localhost"]
)
def test_url_accepts_https_and_local_http(url: str) -> None:
	assert validate_url(url) == url.rstrip("/")


def test_url_refuses_plain_http_to_a_remote_host() -> None:
	with pytest.raises(CentralError, match="https://"):
		validate_url("http://central.test")


def test_redirect_is_refused_so_credentials_stay_on_the_host() -> None:
	class Redirect(BaseHTTPRequestHandler):
		def do_GET(self) -> None:
			self.send_response(302)
			self.send_header("Location", "https://other.test/login")
			self.end_headers()

		def log_message(self, format, *args) -> None:
			pass

	server = HTTPServer(("127.0.0.1", 0), Redirect)
	thread = threading.Thread(target=server.handle_request)
	thread.start()
	client = CentralClient(f"http://localhost:{server.server_port}", session_id="sid")
	try:
		with pytest.raises(CentralError, match=re.escape("https://other.test/login")):
			client.get("anything")
	finally:
		thread.join()
		server.server_close()


def test_get_encodes_query_and_post_sends_json() -> None:
	client = make_client({"read": None, "write": None})

	client.get("read", flag=True, names=["a"], skipped=None)
	client.post("write", flag=True, skipped=None)

	assert read_params(client.requests[0][1]) == {"flag": "1", "names": '["a"]'}
	assert client.requests[1][1].data == b'{"flag": true}'


def test_call_without_credentials_fails_before_the_request() -> None:
	client = make_client({}, session_id=None)

	with pytest.raises(CentralError, match="not signed in"):
		client.get("anything")
	assert client.requests == []


def test_error_reads_server_messages_without_html() -> None:
	messages = json.dumps([json.dumps({"message": "Server <strong>web-1</strong> is not available."})])
	response = error_response(417, {"exc_type": "ValidationError", "_server_messages": messages})

	assert get_error_message(response) == "Server web-1 is not available."


def test_error_for_rejected_credentials_says_how_to_sign_in() -> None:
	message = get_error_message(error_response(401, {"exc_type": "AuthenticationError"}))

	assert "fcloud auth login" in message


def test_error_for_an_expired_session_says_how_to_sign_in() -> None:
	messages = json.dumps([json.dumps({"message": "Login to access"})])
	response = error_response(403, {"exc_type": "PermissionError", "_server_messages": messages})

	assert "fcloud auth login" in get_error_message(response)


@pytest.mark.parametrize("body", ["<html>Bad Gateway</html>", "[]"])
def test_error_without_a_json_object_names_the_status(body: str) -> None:
	assert get_error_message(error_response(502, body)) == "Central returned HTTP 502."


def test_sign_in_keeps_the_session_cookie_and_ignores_guest() -> None:
	client = make_client({}, session_id=None)
	headers = Message()
	headers["Set-Cookie"] = "sid=Guest; Path=/"
	client.read_session_cookie(headers)
	assert client.session_id is None

	headers["Set-Cookie"] = "sid=abc123; Path=/; HttpOnly"
	client.read_session_cookie(headers)
	assert client.session_id == "abc123"


def test_require_team_picks_the_only_active_team() -> None:
	teams = [{"name": "acme", "status": "Active"}, {"name": "old", "status": "Suspended"}]
	client = make_client({"central.api.identity.my_teams": teams})

	assert client.require_team() == "acme"


def test_require_team_refuses_to_guess_between_teams() -> None:
	teams = [{"name": "acme", "status": "Active"}, {"name": "beta", "status": "Active"}]
	client = make_client({"central.api.identity.my_teams": teams})

	with pytest.raises(CentralError, match="fcloud team use"):
		client.require_team()
