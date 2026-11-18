# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import datetime

import frappe

from central.billing.tests.utils import BillingTestCase as IntegrationTestCase


class TestGatewayEventTime(IntegrationTestCase):
	"""Each gateway's event time is read in the system time zone, so delivery delay is exact."""

	def _system(self, *utc):
		return frappe.utils.convert_utc_to_system_timezone(datetime.datetime(*utc)).replace(tzinfo=None)

	def test_unix_seconds_and_iso_times_read_the_same_moment(self):
		from central.billing.gateways.base import event_time

		moment = self._system(2026, 11, 16, 1, 57, 0)
		self.assertEqual(event_time(1794794220), moment)
		self.assertEqual(event_time("2026-11-16T01:57:00.000Z"), moment)
		self.assertEqual(event_time("2026-11-16T07:27:00+05:30"), moment)

	def test_a_missing_or_unreadable_time_is_none(self):
		from central.billing.gateways.base import event_time

		self.assertIsNone(event_time(None))
		self.assertIsNone(event_time("not a time"))

	def test_stripe_and_paypal_events_carry_their_time(self):
		from central.billing.gateways.paypal_adapter import PayPalAdapter
		from central.billing.gateways.stripe_adapter import StripeAdapter

		stripe_event = StripeAdapter.parse_webhook_event(
			None, {"id": "evt_1", "type": "x", "created": 1794794220}
		)
		paypal_event = PayPalAdapter.parse_webhook_event(
			None, {"id": "WH-1", "event_type": "x", "create_time": "2026-11-16T01:57:00Z"}
		)
		self.assertEqual(stripe_event.occurred_at, self._system(2026, 11, 16, 1, 57, 0))
		self.assertEqual(paypal_event.occurred_at, self._system(2026, 11, 16, 1, 57, 0))
