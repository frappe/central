import json

import keyring
import pytest
from conftest import URL

from fcloud.cli import main
from fcloud.profiles import KEYRING_SERVICE, ProfileStore

# The fake Central mocks more endpoints than one test calls.
pytestmark = pytest.mark.httpx2(assert_all_called=False)


def run(*arguments: str) -> int:
	with pytest.raises(SystemExit) as exit:
		main(list(arguments))
	return exit.value.code


def get_tokens(name: str = "central.test") -> dict:
	return json.loads(keyring.get_password(KEYRING_SERVICE, name))


def test_oauth_login_registers_a_public_client_and_signs_in_with_pkce(central, capsys):
	assert run("auth", "login", "central.test") == 0

	profile = ProfileStore().get()
	assert (profile.url, profile.method, profile.client_id) == (URL, "oauth", "client-1")
	assert central.registrations[0]["token_endpoint_auth_method"] == "none"
	assert central.authorize_params["code_challenge_method"] == "S256"
	assert get_tokens()["access_token"] == "access-1"
	assert "as user@example.com" in capsys.readouterr().out


def test_login_again_reuses_the_registered_client(central):
	run("auth", "login", URL)
	run("auth", "login", URL)

	assert len(central.registrations) == 1


def test_denied_sign_in_fails(central, capsys):
	central.redirect_override = {"error": "access_denied"}

	assert run("auth", "login", URL) == 1
	assert "Sign-in failed: access_denied" in capsys.readouterr().err
	assert not ProfileStore().profiles


def test_redirect_of_another_login_is_rejected(central, capsys):
	central.redirect_override = {"code": "code-1", "state": "someone-else"}

	assert run("auth", "login", URL) == 1
	assert "Sign-in failed" in capsys.readouterr().err
	assert not central.grants


def test_site_without_oauth_points_to_api_key(central, capsys):
	central.metadata.respond(404)

	assert run("auth", "login", URL) == 1
	assert "--api-key" in capsys.readouterr().err


def test_plain_http_to_a_remote_host_is_refused(capsys):
	assert run("auth", "login", "http://central.example.com") == 1
	assert "https://" in capsys.readouterr().err


def test_api_key_login(central, monkeypatch):
	answers = iter(["key1", "secret1"])
	monkeypatch.setattr("typer.prompt", lambda *arguments, **options: next(answers))

	assert run("auth", "login", URL, "--api-key") == 0
	assert ProfileStore().get().method == "api_key"
	assert keyring.get_password(KEYRING_SERVICE, "central.test") == "key1:secret1"


def test_logout_revokes_the_session_and_forgets_it(central):
	run("auth", "login", URL)

	assert run("auth", "logout", "central.test") == 0
	assert central.revoked[0]["token"] == "refresh-1"
	assert keyring.get_password(KEYRING_SERVICE, "central.test") is None
	assert not ProfileStore().profiles


def test_logout_still_forgets_the_session_when_central_is_down(central, capsys):
	run("auth", "login", URL)
	central.metadata.respond(503)

	assert run("auth", "logout", "central.test") == 0
	assert "Couldn't revoke" in capsys.readouterr().out
	assert not ProfileStore().profiles
