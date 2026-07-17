from __future__ import annotations

from typing import Protocol

import frappe
from frappe import _


class ServiceDriver(Protocol):
	"""One managed-service executor integration. Central owns entitlement, state and
	billing; a driver only talks to the executor (Grove, Satellite, ...)."""

	key: str

	def provision_site(self, backend, site: str, options: dict) -> dict: ...

	def revoke_site(self, backend, api_key: str) -> None: ...


def get_driver(handler_key: str) -> ServiceDriver:
	"""Resolve a shipped driver by its code key. Drivers are code, never a
	database-supplied import path."""
	from central.services.drivers.grove import GroveDriver

	drivers: dict[str, ServiceDriver] = {GroveDriver.key: GroveDriver()}

	driver = drivers.get(handler_key)
	if not driver:
		frappe.throw(_("No service driver registered for '{0}'.").format(handler_key))

	return driver
