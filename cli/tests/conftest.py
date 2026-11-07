import json
import urllib.parse
from email.message import Message
from typing import Any

import pytest

from frappe_cloud_cli import context, main
from frappe_cloud_cli.client import CentralClient, Response


class FakeCentral(CentralClient):
	"""Answers each method from `routes` and records the requests, so no test reaches a network."""

	def __init__(self, *args: Any, routes: dict, requests: list, **kwargs: Any) -> None:
		super().__init__(*args, **kwargs)
		self.routes = routes
		self.requests = requests

	def send(self, request) -> Response:
		method = urllib.parse.urlparse(request.full_url).path.removeprefix("/api/method/")
		self.requests.append((method, request))
		answer = self.routes[method]
		if callable(answer):
			answer = answer(read_params(request))
		if isinstance(answer, Response):
			return answer
		return Response(200, Message(), json.dumps({"message": answer}).encode())


def read_params(request) -> dict:
	if request.data:
		return json.loads(request.data)
	query = urllib.parse.urlparse(request.full_url).query
	return {key: values[0] for key, values in urllib.parse.parse_qs(query).items()}


class Central:
	"""Runs `central` commands against the fake routes."""

	def __init__(self, capsys: pytest.CaptureFixture) -> None:
		self.capsys = capsys
		self.routes: dict = {}
		self.requests: list = []

	def run(self, *argv: str) -> tuple[int, str, str]:
		code = main.main(list(argv))
		captured = self.capsys.readouterr()
		return code, captured.out, captured.err

	def params(self, method: str) -> dict:
		"""The parameters of the last call to `method`."""
		return next(read_params(request) for name, request in reversed(self.requests) if name == method)

	def called(self, method: str) -> bool:
		return any(name == method for name, _ in self.requests)


@pytest.fixture
def central(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys) -> Central:
	fake = Central(capsys)
	monkeypatch.setenv("FRAPPE_CLOUD_CONFIG", str(tmp_path / "config.json"))
	monkeypatch.setenv("FRAPPE_CLOUD_URL", "https://central.test")
	monkeypatch.setenv("FRAPPE_CLOUD_API_KEY", "key")
	monkeypatch.setenv("FRAPPE_CLOUD_API_SECRET", "secret")
	monkeypatch.setenv("FRAPPE_CLOUD_TEAM", "acme")
	monkeypatch.setattr(
		context,
		"CentralClient",
		lambda *args, **kwargs: FakeCentral(*args, routes=fake.routes, requests=fake.requests, **kwargs),
	)
	return fake
