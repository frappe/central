# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The IP sanitizer that guards the country lookup against spoofed/malformed
X-Forwarded-For input."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.geo import IP_COUNTRY_TTL_SECONDS, _clean_public_ip, get_country_from_ip


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


class TestCountryLookup(IntegrationTestCase):
	"""The cached lookup itself. `in_test` short-circuits it, so every case clears that
	flag to exercise the real path."""

	def setUp(self):
		frappe.flags.in_test = False
		self.addCleanup(setattr, frappe.flags, "in_test", True)
		self.ip = "49.207.0.1"
		frappe.cache.delete_value(f"ip_country:{self.ip}")
		self.addCleanup(frappe.cache.delete_value, f"ip_country:{self.ip}")

	def test_a_miss_looks_up_and_caches_with_a_ttl(self):
		answer = {"status": "success", "country": "India", "countryCode": "IN"}
		with patch("central.geo._lookup_ip", return_value=answer) as lookup:
			self.assertEqual(get_country_from_ip(self.ip), "India")

		lookup.assert_called_once_with(self.ip)
		self.assertEqual(frappe.cache.get_value(f"ip_country:{self.ip}"), answer)
		self.assertGreater(frappe.cache.ttl(frappe.cache.make_key(f"ip_country:{self.ip}")), 0)
		self.assertLessEqual(
			frappe.cache.ttl(frappe.cache.make_key(f"ip_country:{self.ip}")), IP_COUNTRY_TTL_SECONDS
		)

	def test_a_hit_does_not_look_up_again(self):
		frappe.cache.set_value(f"ip_country:{self.ip}", {"country": "India"}, expires_in_sec=60)
		with patch("central.geo._lookup_ip") as lookup:
			self.assertEqual(get_country_from_ip(self.ip), "India")

		lookup.assert_not_called()

	def test_a_failed_lookup_returns_none_and_is_not_cached(self):
		with patch("central.geo._lookup_ip", return_value={}):
			self.assertIsNone(get_country_from_ip(self.ip))

		self.assertIsNone(frappe.cache.get_value(f"ip_country:{self.ip}"))

	def test_a_private_ip_never_reaches_the_lookup(self):
		with patch("central.geo._lookup_ip") as lookup:
			self.assertIsNone(get_country_from_ip("127.0.0.1"))

		lookup.assert_not_called()
