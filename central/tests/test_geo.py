# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The IP sanitizer that guards the country lookup against spoofed/malformed
X-Forwarded-For input."""

from frappe.tests import IntegrationTestCase

from central.geo import _clean_public_ip


class TestCleanPublicIP(IntegrationTestCase):
	def test_valid_public_ipv4_passes_through_canonicalised(self):
		self.assertEqual(_clean_public_ip("49.207.0.1"), "49.207.0.1")

	def test_valid_public_ipv6_is_canonicalised(self):
		# Upper case + zero-groups collapse to the library's canonical form
		# (Google public DNS, a genuinely global address).
		self.assertEqual(_clean_public_ip("2001:4860:4860:0000:0000:0000:0000:8888"), "2001:4860:4860::8888")

	def test_xforwarded_for_chain_takes_the_client_hop(self):
		self.assertEqual(_clean_public_ip("49.207.0.1, 10.0.0.5, 172.16.0.1"), "49.207.0.1")

	def test_url_injection_payload_is_rejected(self):
		# A value that would otherwise land inside the outbound lookup URL.
		for payload in ("49.207.0.1/../admin", "1.2.3.4?x=y", "1.2.3.4 8.8.8.8", "evil.example.com", ""):
			with self.subTest(payload=payload):
				self.assertIsNone(_clean_public_ip(payload))

	def test_private_and_loopback_are_dropped(self):
		for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "::1", "169.254.0.1", "0.0.0.0"):
			with self.subTest(ip=ip):
				self.assertIsNone(_clean_public_ip(ip))

	def test_none_and_blank_return_none(self):
		self.assertIsNone(_clean_public_ip(None))
		self.assertIsNone(_clean_public_ip("   "))
