import base64
import json
import os
from email.message import Message

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from frappe_cloud.client import Response
from frappe_cloud.commands.wireguard import generate_key_pair

CREATE = "central.api.wireguard.create_wireguard_device"
DEVICE = {
	"name": "WG-1",
	"title": "Ada's Laptop",
	"address": "fd00::10/128",
	"allowed_ips": "fd00::/64\nfd01::/64",
	"endpoint": "gateway.test:51820",
	"gateway_public_key": "GATEWAY=",
}


def test_key_pair_public_key_matches_the_private_key() -> None:
	private_key, public_key = generate_key_pair()

	derived = X25519PrivateKey.from_private_bytes(base64.b64decode(private_key)).public_key()
	assert base64.b64encode(derived.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode() == public_key


def test_create_sends_only_the_public_key_and_writes_a_private_config(central, tmp_path, monkeypatch) -> None:
	monkeypatch.chdir(tmp_path)
	central.routes[CREATE] = DEVICE

	code, out, _ = central.run("wireguard", "create", "--region", "blr1", "--title", "Ada's Laptop")

	path = tmp_path / "ada-s-laptop.conf"
	config = path.read_text()
	private_key = config.split("PrivateKey = ")[1].splitlines()[0]
	assert code == 0
	assert "sudo wg-quick up" in out
	assert private_key not in str(central.params(CREATE))
	assert "AllowedIPs = fd00::/64, fd01::/64" in config
	assert "PublicKey = GATEWAY=" in config
	assert os.stat(path).st_mode & 0o777 == 0o600


def test_create_never_replaces_an_existing_config(central, tmp_path) -> None:
	path = tmp_path / "wg0.conf"
	path.write_text("keep")
	central.routes[CREATE] = DEVICE

	code, _, err = central.run(
		"wireguard", "create", "--region", "blr1", "--title", "laptop", "--output", str(path)
	)

	assert code == 1
	assert "already exists" in err
	assert path.read_text() == "keep"
	assert not central.has_called(CREATE)


def test_create_removes_the_config_when_central_refuses(central, tmp_path) -> None:
	path = tmp_path / "wg0.conf"
	central.routes[CREATE] = error_response(417, "The gateway is full.")

	code, _, err = central.run(
		"wireguard", "create", "--region", "blr1", "--title", "laptop", "--output", str(path)
	)

	assert code == 1
	assert "The gateway is full." in err
	assert not path.exists()


def error_response(status: int, message: str) -> Response:
	body = {"exc_type": "ValidationError", "_server_messages": json.dumps([json.dumps({"message": message})])}
	return Response(status, Message(), json.dumps(body).encode())
