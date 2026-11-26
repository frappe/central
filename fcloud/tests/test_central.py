import json
import time

import httpx
import keyring
import pytest
from conftest import URL

from fcloud.auth.credentials import ApiKeyCredential, OAuthCredential
from fcloud.central import Central
from fcloud.errors import CentralError, LoginError
from fcloud.profiles import KEYRING_SERVICE

# The fake Central mocks more endpoints than one test calls.
pytestmark = pytest.mark.httpx2(assert_all_called=False)


@pytest.fixture
def signed_in(central) -> Central:
	credential = OAuthCredential.log_in("central.test", URL)
	return Central(URL, credential)


def test_expiring_token_is_refreshed_before_the_request(central, signed_in):
	signed_in.credential.tokens.expires_at = time.time()

	assert signed_in.get_user() == "user@example.com"
	assert central.grants == ["authorization_code", "refresh_token"]
	assert json.loads(keyring.get_password(KEYRING_SERVICE, "central.test"))["refresh_token"] == "refresh-2"


def test_rejected_token_is_retried_once_after_refresh(central, signed_in):
	central.access_token = "revoked-on-central"

	assert signed_in.get_user() == "user@example.com"
	assert central.grants[-1] == "refresh_token"


def test_token_rotated_by_another_process_is_reused(central, signed_in):
	other_process = Central(URL, OAuthCredential.from_profile(signed_in.credential.profile))
	other_process.credential.refresh()

	assert signed_in.get_user() == "user@example.com"
	assert central.grants == ["authorization_code", "refresh_token"]


def test_dead_refresh_token_asks_to_log_in_again(central, signed_in):
	central.access_token, central.refresh_token = "revoked", "rotated-elsewhere"

	with pytest.raises(LoginError, match="fcloud auth login"):
		signed_in.get_user()


def test_rejected_api_key_is_not_retried(httpx2_mock):
	messages = json.dumps([json.dumps({"message": "No access"})])
	route = httpx2_mock.get(f"{URL}/api/method/frappe.auth.get_logged_user").respond(
		403, json={"exc_type": "PermissionError", "_server_messages": messages}
	)

	with pytest.raises(CentralError, match="No access") as raised:
		Central(URL, ApiKeyCredential("key", "secret")).get_user()
	assert raised.value.status == 403
	assert route.call_count == 1


def test_environment_credentials_take_precedence(httpx2_mock, monkeypatch):
	monkeypatch.setenv("FCLOUD_URL", URL)
	monkeypatch.setenv("FCLOUD_API_KEY", "key")
	monkeypatch.setenv("FCLOUD_API_SECRET", "secret")
	route = httpx2_mock.get(f"{URL}/api/method/frappe.auth.get_logged_user").respond(
		json={"message": "ci@example.com"}
	)

	assert Central.connect().get_user() == "ci@example.com"
	assert route.calls.last.request.headers["Authorization"] == "token key:secret"


def test_unreadable_error_keeps_the_status(httpx2_mock):
	httpx2_mock.get(f"{URL}/api/method/frappe.auth.get_logged_user").mock(
		return_value=httpx.Response(502, text="<html>")
	)

	with pytest.raises(CentralError) as raised:
		Central(URL, ApiKeyCredential("key", "secret")).get_user()
	assert raised.value.status == 502
