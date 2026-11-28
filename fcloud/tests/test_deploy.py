import json

import httpx
import pytest
from conftest import URL

from fcloud.auth.credentials import ApiKeyCredential
from fcloud.central import Central
from fcloud.deploy.app import DeployApp, RepositoryConnection
from fcloud.deploy.logs import DeployLog
from fcloud.deploy.repository import to_owner_and_name
from fcloud.errors import FcloudError

API = f"{URL}/api/method/central.deploy.api"


@pytest.fixture
def router(httpx2_mock):
	return httpx2_mock


def connect() -> Central:
	return Central(URL, ApiKeyCredential("key", "secret"))


@pytest.mark.parametrize(
	"remote",
	[
		"git@github.com:frappe/demo.git",
		"https://github.com/frappe/demo.git",
		"https://github.com/frappe/demo/",
		"frappe/demo",
	],
)
def test_repository_from_remote(remote):
	assert to_owner_and_name(remote) == "frappe/demo"


def test_unconnected_repository_points_to_launch(router):
	router.get(f"{URL}/api/resource/Deploy App").respond(json={"data": []})

	with pytest.raises(FcloudError, match="fcloud launch"):
		DeployApp.find(connect(), "frappe/demo", "main")


def test_connection_waits_while_github_is_pending(router):
	route = router.post(f"{API}.complete_repository_connection")
	route.side_effect = [
		httpx.Response(417, json={"exception": "Install the GitHub App first."}),
		httpx.Response(
			200, json={"message": {"name": "app-1", "repository": "frappe/demo", "branch": "main"}}
		),
	]
	connection = RepositoryConnection(connect(), "https://github.test/sign-in", "state-1")

	assert connection.get_app() is None
	assert connection.get_app().name == "app-1"


def test_connection_failure_is_raised(router):
	router.post(f"{API}.complete_repository_connection").respond(417, json={"exception": "Region is full."})

	with pytest.raises(FcloudError, match="Region is full"):
		RepositoryConnection(connect(), "https://github.test/sign-in", "state-1").get_app()


def test_log_prints_only_new_lines_and_restarts_after_truncation(router, capsys):
	deploy = {"name": "DR-1", "commit": "abcdef123", "status": "Running", "tasks": [], "release_log": ""}
	router.get(f"{API}.get_deploy_request").side_effect = [
		httpx.Response(200, json={"message": {**deploy, "build_log": "one\n"}}),
		httpx.Response(200, json={"message": {**deploy, "build_log": "one\ntwo\n"}}),
		httpx.Response(200, json={"message": {**deploy, "build_log": "[cut]\nthree\n"}}),
	]
	log = DeployLog(connect(), "DR-1")
	for _ in range(3):
		log.show()

	lines = [line.strip() for line in capsys.readouterr().out.splitlines()]
	assert lines == [
		"==> DR-1 (abcdef12): Running",
		"build | one",
		"build | two",
		"build | [cut]",
		"build | three",
	]


def test_secrets_are_set_in_one_change(router):
	route = router.post(f"{API}.update_app_secrets").respond(json={"message": ["A", "B"]})
	deploy_app = DeployApp(connect(), {"name": "app-1", "repository": "frappe/demo", "branch": "main"})

	assert deploy_app.update_secrets(secrets={"A": "1", "B": "2"}) == ["A", "B"]
	assert json.loads(route.calls.last.request.content) == {"name": "app-1", "secrets": {"A": "1", "B": "2"}}
