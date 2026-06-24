"""Unit tests for the WireGuard hub rule/config generation.

Run with bare `python3 -m unittest central.test_wireguard` from scripts/lib: no
Frappe, no site, no host, no wg. These cover the argv/config construction that drives
ensure_interface()/add_peer()/remove_peer() without touching the host.
"""

import unittest

from central import wireguard as wg

PEER = "abc123def456ghi789jkl012mno345pqr678stu901v="
TUNNEL_IP = "10.88.0.2/32"
ENDPOINT = "203.0.113.7:51820"


class TestInterfaceConf(unittest.TestCase):
	def test_interface_section_has_key_address_port(self):
		conf = wg.interface_conf("PRIVKEY==", "10.88.0.1/16", 51820)
		self.assertIn("[Interface]", conf)
		self.assertIn("PrivateKey = PRIVKEY==", conf)
		self.assertIn("Address = 10.88.0.1/16", conf)
		self.assertIn("ListenPort = 51820", conf)

	def test_no_peer_and_no_saveconfig(self):
		# Peers are added at runtime and persisted by `wg-quick save`; SaveConfig is
		# deliberately omitted so a stray `wg-quick down` can't rewrite the file.
		conf = wg.interface_conf("K", "10.88.0.1/16", 51820)
		self.assertNotIn("[Peer]", conf)
		self.assertNotIn("SaveConfig", conf)


class TestPeerSetArgv(unittest.TestCase):
	def test_full_peer_with_endpoint_and_keepalive(self):
		argv = wg.peer_set_argv("wg0", PEER, TUNNEL_IP, ENDPOINT, 25)
		self.assertEqual(
			argv,
			["set", "wg0", "peer", PEER, "allowed-ips", TUNNEL_IP,
			 "endpoint", ENDPOINT, "persistent-keepalive", "25"],
		)  # fmt: skip

	def test_endpoint_omitted_when_none(self):
		argv = wg.peer_set_argv("wg0", PEER, TUNNEL_IP, None, None)
		self.assertEqual(argv, ["set", "wg0", "peer", PEER, "allowed-ips", TUNNEL_IP])
		self.assertNotIn("endpoint", argv)
		self.assertNotIn("persistent-keepalive", argv)

	def test_keepalive_zero_is_emitted(self):
		# 0 is a meaningful keepalive value (disable); only None omits the flag.
		argv = wg.peer_set_argv("wg0", PEER, TUNNEL_IP, ENDPOINT, 0)
		self.assertIn("persistent-keepalive", argv)
		self.assertEqual(argv[-1], "0")


class TestPeerRemoveArgv(unittest.TestCase):
	def test_remove(self):
		self.assertEqual(
			wg.peer_remove_argv("wg0", PEER),
			["set", "wg0", "peer", PEER, "remove"],
		)


if __name__ == "__main__":
	unittest.main()
