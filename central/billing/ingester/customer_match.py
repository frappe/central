# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Find a team's customer that already exists in the accounting system, so the sync uses it
again instead of making a second one. Press v1 made most of these customers."""

from dataclasses import dataclass

import frappe
from frappe import _

from central.billing.ingester import connection


@dataclass
class Match:
	customer: str
	address: str | None
	contact: str | None


@dataclass
class Candidate:
	customer: str
	contact: str


def find_existing(profile) -> Match | None:
	"""The one customer that is this team's, or None when there is none.

	1. A contact with the team owner's or the billing email is linked to the customer.
	2. The customer has the same name, ignoring case and spaces, and the same currency.
	3. One of its addresses is in the same city and country, ignoring case.
	4. More than one such customer is not guessed: an operator picks one.
	"""
	candidates = _candidates(emails_of(profile))
	matches = [match for candidate in candidates if (match := _match(profile, candidate))]
	if len(matches) > 1:
		frappe.throw(
			_(
				"Team {0} matches more than one customer in the accounting system: {1}. Pick one with Use Existing Customer."
			).format(profile.team, ", ".join(m.customer for m in matches))
		)
	return matches[0] if matches else None


def match_customer(profile, customer: str) -> Match:
	"""The customer an operator picked, with its address and contact when they match the team."""
	record = connection.fetch("Customer", customer)
	if not record:
		frappe.throw(_("Customer {0} does not exist in the accounting system.").format(customer))
	if record.get("default_currency") != profile.currency:
		frappe.throw(
			_("Customer {0} bills in {1}, but team {2} pays in {3}.").format(
				customer, record.get("default_currency"), profile.team, profile.currency
			)
		)
	contact = next((c.contact for c in _candidates(emails_of(profile)) if c.customer == customer), None)
	return Match(customer, _address_in_city(profile, customer), contact)


def emails_of(profile) -> list[str]:
	"""The team owner's email and the billing email, the ones the contact carries."""
	owner = profile.team_owner or frappe.db.get_value("Team", profile.team, "owner_user")
	return [email for email in dict.fromkeys([owner, profile.email]) if email]


def _candidates(emails: list[str]) -> list[Candidate]:
	"""Each customer linked to a contact with one of `emails`, once."""
	if not emails:
		return []
	found = {}
	contacts = connection.find("Contact", [["Contact Email", "email_id", "in", emails]], ["name"])
	for name in dict.fromkeys(row.name for row in contacts):
		for link in (connection.fetch("Contact", name) or {}).get("links") or []:
			if link.get("link_doctype") == "Customer":
				found.setdefault(link["link_name"], Candidate(link["link_name"], name))
	return list(found.values())


def _match(profile, candidate: Candidate) -> Match | None:
	record = connection.fetch("Customer", candidate.customer) or {}
	if not _is_same(record.get("customer_name"), profile.legal_name):
		return None
	if record.get("default_currency") != profile.currency:
		return None
	address = _address_in_city(profile, candidate.customer)
	return Match(candidate.customer, address, candidate.contact) if address else None


def _address_in_city(profile, customer: str) -> str | None:
	addresses = connection.find(
		"Address",
		[["Dynamic Link", "link_doctype", "=", "Customer"], ["Dynamic Link", "link_name", "=", customer]],
		["name", "city", "country"],
	)
	for address in addresses:
		if _is_same(address.get("city"), profile.city) and _is_same(address.get("country"), profile.country):
			return address.name
	return None


def _is_same(left: str | None, right: str | None) -> bool:
	return bool(left and right) and " ".join(left.split()).casefold() == " ".join(right.split()).casefold()
