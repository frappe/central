# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""The month's USD rate is read from a rate API, and anything but a clear rate is no rate."""

import datetime
from unittest.mock import MagicMock, patch

import requests
from frappe.tests import UnitTestCase

from central.billing.revenue import exchange_rate_feed

JUNE_1 = datetime.date(2026, 6, 1)
ANSWER = {"date": "2026-06-01", "base": "USD", "quote": "INR", "rate": 95.01}


def answering(body=None, status: int = 200, json_error: bool = False):
	response = MagicMock(status_code=status)
	response.json.side_effect = ValueError("not json") if json_error else None
	response.json.return_value = body
	return patch.object(exchange_rate_feed.requests, "get", return_value=response)


class TestExchangeRateFeed(UnitTestCase):
	def setUp(self):
		url = patch.object(exchange_rate_feed, "exchange_rate_url", return_value="https://rates.test/v2")
		url.start()
		self.addCleanup(url.stop)

	def test_a_rate_is_read_for_the_day_asked(self):
		with answering(ANSWER) as get:
			found = exchange_rate_feed.feed_rate("USD", "INR", JUNE_1)
		self.assertEqual((found.rate, found.rate_date, found.source), (95.01, JUNE_1, "rates.test"))
		self.assertEqual(get.call_args.args[0], "https://rates.test/v2/rate/USD/INR")
		self.assertEqual(get.call_args.kwargs["params"], {"date": "2026-06-01"})
		self.assertEqual(get.call_args.kwargs["timeout"], exchange_rate_feed.TIMEOUT_SECONDS)

	def test_the_rate_date_is_the_apis_date(self):
		with answering({**ANSWER, "date": "2026-05-29"}):
			found = exchange_rate_feed.feed_rate("USD", "INR", JUNE_1)
		self.assertEqual(found.rate_date, datetime.date(2026, 5, 29))

	def test_anything_but_a_clear_rate_is_no_rate(self):
		cases = {
			"not found": answering({"message": "not found"}, status=404),
			"server error": answering(ANSWER, status=500),
			"not json": answering(json_error=True),
			"a list": answering([ANSWER]),
			"zero": answering({**ANSWER, "rate": 0}),
			"negative": answering({**ANSWER, "rate": -1}),
			"no rate": answering({k: v for k, v in ANSWER.items() if k != "rate"}),
			"no date": answering({k: v for k, v in ANSWER.items() if k != "date"}),
			"bad date": answering({**ANSWER, "date": "soon"}),
			"number date": answering({**ANSWER, "date": 20260601}),
			"empty date": answering({**ANSWER, "date": ""}),
			"other quote": answering({**ANSWER, "quote": "EUR"}),
			"other base": answering({**ANSWER, "base": "EUR"}),
		}
		for case, response in cases.items():
			with self.subTest(case), response:
				self.assertIsNone(exchange_rate_feed.feed_rate("USD", "INR", JUNE_1))

	def test_an_api_that_does_not_answer_is_no_rate(self):
		with patch.object(exchange_rate_feed.requests, "get", side_effect=requests.Timeout("slow")):
			self.assertIsNone(exchange_rate_feed.feed_rate("USD", "INR", JUNE_1))

	def test_no_url_asks_nothing(self):
		with patch.object(exchange_rate_feed, "exchange_rate_url", return_value=""), answering(ANSWER) as get:
			self.assertIsNone(exchange_rate_feed.feed_rate("USD", "INR", JUNE_1))
		get.assert_not_called()
