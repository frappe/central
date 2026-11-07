import json
import os
import uuid
from email.message import Message

import pytest

from frappe_cloud_cli.client import Response
from frappe_cloud_cli.commands import server
from frappe_cloud_cli.config import Config
from frappe_cloud_cli.errors import CentralError

REGISTRY = "central.api.servers.registry"
WEB = {
	"resource_id": "vm-1",
	"title": "web",
	"region": "blr1",
	"status": "Running",
	"pending_action": None,
	"plan_title": "Small",
	"public_ipv4": "203.0.113.4",
}


def registry(*servers: dict) -> dict:
	return {"servers": list(servers), "sites": [], "creations": []}


def test_server_list_shows_the_pending_action_as_status(central) -> None:
	central.routes[REGISTRY] = registry({**WEB, "pending_action": "Stopping"})

	code, out, _ = central.run("server", "list")

	assert code == 0
	assert out.splitlines()[1].split() == ["vm-1", "web", "blr1", "Stopping", "Small", "203.0.113.4"]
	assert central.params(REGISTRY) == {"team": "acme"}


def test_json_flag_prints_the_raw_rows(central) -> None:
	central.routes[REGISTRY] = registry(WEB)

	_, out, _ = central.run("server", "list", "--json")

	assert json.loads(out) == [WEB]


def test_server_found_by_title_and_ambiguous_title_fails(central) -> None:
	central.routes[REGISTRY] = registry(WEB, {**WEB, "resource_id": "vm-2"})
	central.routes["central.api.servers.rename_server"] = {}

	code, _, err = central.run("server", "rename", "web", "api")

	assert code == 1
	assert "2 servers have the title 'web'" in err
	assert not central.called("central.api.servers.rename_server")


def test_create_server_uses_the_newest_image_and_an_idempotency_key(central) -> None:
	images = [{"id": "old", "created_at": 1}, {"id": "new", "created_at": 2}]
	central.routes["central.api.images.list_images"] = {"items": images}
	central.routes["central.api.servers.create_server"] = {"action": "RA-1", "status": "Queued"}

	code, out, _ = central.run(
		"server",
		"create",
		"web",
		"--region",
		"blr1",
		"--plan",
		"small",
		"--offering",
		"ubuntu",
		"--ssh-key",
		"k1",
	)

	params = central.params("central.api.servers.create_server")
	assert code == 0
	assert params["image_id"] == "new"
	assert params["ssh_key_ids"] == ["k1"]
	assert uuid.UUID(params["request_key"])
	assert "RA-1 is Queued" in out


def test_terminate_without_a_terminal_needs_yes(central, monkeypatch) -> None:
	central.routes[REGISTRY] = registry(WEB)
	central.routes["central.api.servers.terminate_server"] = {"action": "RA-2", "status": "Queued"}
	monkeypatch.setattr("sys.stdin.isatty", lambda: False)

	code, _, err = central.run("server", "terminate", "vm-1")
	assert code == 1
	assert "--yes" in err
	assert not central.called("central.api.servers.terminate_server")

	code, _, _ = central.run("server", "terminate", "vm-1", "--yes", "--snapshot")
	assert code == 0
	assert central.params("central.api.servers.terminate_server")["take_snapshot"] is True


def test_wait_raises_the_action_error(central, monkeypatch) -> None:
	states = iter(["Dispatching", "Failed"])
	central.routes["central.api.servers.action_status"] = lambda params: {
		"action": "RA-1",
		"status": next(states),
		"error": {"message": "The region is full."},
	}
	monkeypatch.setattr(server.time, "sleep", lambda seconds: None)

	code, _, err = central.run("server", "wait", "RA-1")

	assert code == 1
	assert "RA-1 is Failed. The region is full." in err


@pytest.mark.parametrize(
	("overview", "address"),
	[
		({"public_ipv6": "2001:db8::1", "public_ipv4": "203.0.113.4"}, "2001:db8::1"),
		({"has_wireguard_access": 1, "ipv6_address": "fd00::5"}, "fd00::5"),
	],
)
def test_ssh_address_prefers_public_then_wireguard(overview: dict, address: str) -> None:
	assert server.get_ssh_address(overview) == address


def test_ssh_refuses_a_user_that_ssh_reads_as_an_option(central, monkeypatch) -> None:
	central.routes[REGISTRY] = registry(WEB)
	central.routes["central.api.servers.server_overview"] = {"server": WEB}
	monkeypatch.setattr(server.os, "execvp", lambda *args: pytest.fail("ssh must not run"))

	code, _, err = central.run("server", "ssh", "web", "--user=-oProxyCommand=x")

	assert code == 1
	assert "cannot start with '-'" in err


def test_snapshot_delete_reports_each_failure(central, monkeypatch) -> None:
	central.routes["central.api.snapshots.delete_snapshots"] = {
		"deleted": ["SNAP-1"],
		"failed": {"SNAP-2": "The snapshot is in use."},
	}

	code, out, err = central.run("snapshot", "delete", "SNAP-1", "SNAP-2", "--yes")

	assert code == 1
	assert "Deleting SNAP-1." in out
	assert "SNAP-2: The snapshot is in use." in err


def test_ssh_address_without_a_route_explains_wireguard() -> None:
	with pytest.raises(CentralError, match="fcloud wireguard allow vm-1"):
		server.get_ssh_address({"resource_id": "vm-1", "title": "web", "ipv6_address": "fd00::5"})


def test_login_saves_a_private_session(central, monkeypatch, tmp_path) -> None:
	monkeypatch.delenv("FRAPPE_CLOUD_API_KEY")
	monkeypatch.setattr("sys.stdin.isatty", lambda: True)
	monkeypatch.setattr("builtins.input", lambda: "123456")
	headers = Message()
	headers["Set-Cookie"] = "sid=abc123; Path=/; HttpOnly"
	central.routes["central.api.auth.send_code"] = {"message": "sent"}
	central.routes["central.api.auth.verify_code"] = Response(
		200, headers, json.dumps({"message": {"user": "ada@example.com", "csrf_token": "csrf"}}).encode()
	)

	code, out, _ = central.run("auth", "login", "--email", "ada@example.com")

	config = Config.load()
	assert code == 0
	assert "Signed in to https://central.test as ada@example.com" in out
	assert (config.session_id, config.csrf_token, config.url) == ("abc123", "csrf", "https://central.test")
	assert os.stat(config.path).st_mode & 0o777 == 0o600


def test_save_replaces_a_readable_config_with_a_private_one(tmp_path) -> None:
	path = tmp_path / "config.json"
	path.write_text("{}")
	path.chmod(0o644)

	Config(path=path, session_id="abc123").save()

	assert os.stat(path).st_mode & 0o777 == 0o600
	assert Config.load(path).session_id == "abc123"
	assert list(tmp_path.iterdir()) == [path]


def test_team_use_saves_only_a_team_of_the_user(central) -> None:
	central.routes["central.api.identity.my_teams"] = [{"name": "acme", "status": "Active"}]

	assert central.run("team", "use", "other")[0] == 1
	assert central.run("team", "use", "acme")[0] == 0
	assert Config.load().team == "acme"
