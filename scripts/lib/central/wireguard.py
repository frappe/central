"""WireGuard hub plumbing for Central — the host-side of the tunnel.

Central's Frappe host is the WireGuard hub (central/spec/TUNNEL.md): one `wg0`
interface, one `/32` peer per Atlas, the hub dialing each spoke's public UDP port.
This module is the host slice the three hub scripts (`hub-up`, `hub-peer-add`,
`hub-peer-remove`) share, structured like Atlas's `reserved_ip_nat.py`:

  - the **argv / config builders** (`interface_conf`, `peer_set_argv`,
    `peer_remove_argv`) are pure string construction — unit-testable with bare
    `python3 -m unittest`, no host;
  - only `ensure_keypair`, `ensure_interface`, `add_peer`, `remove_peer` touch the
    host (via `_run`), and they are idempotent — re-running (cold boot, reconcile,
    double register) is a no-op, the same self-healing contract Atlas's host scripts
    keep.

Peers are persisted with `wg-quick save`, which writes the live runtime config
(Interface + every Peer) back to `/etc/wireguard/<iface>.conf`, so a reboot brings
the whole peer set back via `wg-quick@<iface>`.
"""

from __future__ import annotations

from central._run import install_file, run, run_input, run_ok

WG_DIR = "/etc/wireguard"
DEFAULT_INTERFACE = "wg0"


def conf_path(interface: str) -> str:
	return f"{WG_DIR}/{interface}.conf"


# --- pure builders (unit-testable, no host) ---------------------------------


def interface_conf(private_key: str, address: str, listen_port: int) -> str:
	"""The `[Interface]` section of a hub `wg0.conf`. Peers are NOT written here —
	they are added at runtime (`wg set`) and persisted by `wg-quick save`, which
	appends `[Peer]` sections to this file. We deliberately omit `SaveConfig` so an
	accidental `wg-quick down` can't silently rewrite the file; persistence is an
	explicit `save` in `add_peer` / `remove_peer`."""
	return f"[Interface]\nPrivateKey = {private_key}\nAddress = {address}\nListenPort = {listen_port}\n"


def peer_set_argv(
	interface: str,
	public_key: str,
	allowed_ips: str,
	endpoint: str | None = None,
	keepalive: int | None = None,
) -> list[str]:
	"""`wg set <iface> peer <pubkey> allowed-ips <ips> [endpoint <ep>]
	[persistent-keepalive <n>]` — the args after `wg`. `allowed_ips` is passed whole
	(e.g. `10.88.0.2/32`) so the caller owns the mask. `endpoint` is the spoke's
	public `ip:port` (the hub dials it); `keepalive` keeps the session warm through
	the spoke's firewall/NAT."""
	argv = ["set", interface, "peer", public_key, "allowed-ips", allowed_ips]
	if endpoint:
		argv += ["endpoint", endpoint]
	if keepalive is not None:
		argv += ["persistent-keepalive", str(keepalive)]
	return argv


def peer_remove_argv(interface: str, public_key: str) -> list[str]:
	"""`wg set <iface> peer <pubkey> remove` — the args after `wg`."""
	return ["set", interface, "peer", public_key, "remove"]


# --- host functions (idempotent) --------------------------------------------


def _exists_as_root(path: str) -> bool:
	return run_ok("sudo", "test", "-f", path)


def interface_is_up(interface: str) -> bool:
	return run_ok("sudo", "wg", "show", interface)


def ensure_keypair(private_key_path: str) -> str:
	"""Ensure a `0600` WireGuard private key exists at `private_key_path` (generate
	it with `wg genkey` if absent — the private key never leaves the host) and return
	the corresponding public key. Idempotent: an existing key is read, not
	regenerated, so the hub's public key is stable across re-runs."""
	if _exists_as_root(private_key_path):
		private_key = run("sudo", "cat", private_key_path).strip()
	else:
		private_key = run("wg", "genkey").strip()
		install_file(private_key + "\n", private_key_path, mode="0600", sudo=True)
	return run_input("wg", "pubkey", stdin=private_key).strip()


def ensure_interface(interface: str, private_key_path: str, address: str, listen_port: int) -> None:
	"""Idempotently bring up `<interface>` as the hub: write its `wg0.conf` from the
	stored private key (only if absent — re-running must not clobber persisted
	peers), `wg-quick up` it if it isn't already up, and `systemctl enable
	wg-quick@<interface>` for reboot persistence."""
	path = conf_path(interface)
	if not _exists_as_root(path):
		private_key = run("sudo", "cat", private_key_path).strip()
		install_file(interface_conf(private_key, address, listen_port), path, mode="0600", sudo=True)
	if not interface_is_up(interface):
		run("sudo", "wg-quick", "up", interface)
	run("sudo", "systemctl", "enable", f"wg-quick@{interface}")


def add_peer(
	interface: str,
	public_key: str,
	allowed_ips: str,
	endpoint: str | None,
	keepalive: int | None,
) -> None:
	"""Add (or update) a peer and persist it. `wg set` is itself idempotent — re-
	adding the same pubkey updates it in place — and `wg-quick save` writes the live
	config back to disk so the peer survives a reboot."""
	run("sudo", "wg", *peer_set_argv(interface, public_key, allowed_ips, endpoint, keepalive))
	run("sudo", "wg-quick", "save", interface)


def remove_peer(interface: str, public_key: str) -> None:
	"""Remove a peer and persist. Best-effort `wg set ... remove` (a missing peer is
	not an error — a rollback may run after a half-add), then `wg-quick save`."""
	run("sudo", "wg", *peer_remove_argv(interface, public_key), check=False)
	run("sudo", "wg-quick", "save", interface)
