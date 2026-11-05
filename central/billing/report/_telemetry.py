# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import hashlib
import re
from collections import defaultdict

import frappe
from frappe.utils import flt

GIB = 1024**3
CACHE_SECONDS = 15 * 60

# Only ids shaped like Central server names and Atlas host ids reach the query text.
SAFE_ID = re.compile(r"^[A-Za-z0-9-]+$")

SERVER_METRICS = (
	"system_cpu_usage_percent",
	"system_memory_used_bytes",
	"system_disk_used_bytes",
	"system_network_transmit_bytes_per_second",
	"system_network_receive_bytes_per_second",
)
HOST_METRICS = (
	"system_cpu_usage_percent",
	"system_memory_used_bytes",
	"metal_vm_allocated_cpu_millicores",
	"metal_vm_allocated_memory_bytes",
	"metal_vm_allocated_disk_bytes",
)


class Telemetry:
	"""Usage the regions report, read from each region's telemetry source.

	A region names its Insights data source on `Region.telemetry_data_source`. Only servers
	that run the Pilot agent report guest usage. A region without a source, or one that does
	not answer, gives no usage, and `gaps` says which."""

	def __init__(self, days: int = 7):
		self.days = days
		self.gaps: list[str] = []

	def servers(self, servers: list) -> dict[str, dict]:
		"""Average and peak CPU %, memory and disk used (GiB), and bandwidth (GiB a month) per server."""
		usage = {}
		for region, names in _by_region(servers, "name").items():
			rows = self._query(region, _server_sql(names, self.days), f"servers:{region}:{len(names)}")
			for row in rows:
				usage[row[0]] = {
					"cpu_percent": flt(row[1], 1),
					"cpu_peak_percent": flt(row[2], 1),
					"memory_used_gib": flt(row[3], 2),
					"disk_used_gib": flt(row[4], 1),
					"bandwidth_gib_month": flt((flt(row[5]) + flt(row[6])) * 30 * 86400 / GIB, 1),
				}
		return usage

	def hosts(self, machines: list) -> dict[str, dict]:
		"""Per Atlas host: CPU % and memory used, and what Atlas has allocated on it, platform VMs included."""
		usage = {}
		for region, ids in _by_region(machines, "atlas_host_id").items():
			rows = self._query(region, _host_sql(ids), f"hosts:{region}:{len(ids)}")
			for row in rows:
				usage[row[0]] = {
					"cpu_percent": flt(row[1], 1),
					"memory_used_gib": flt(row[2], 1),
					"allocated_vcpus": flt(row[3], 2),
					"allocated_memory_gib": flt(row[4], 1),
					"allocated_disk_gib": flt(row[5], 1),
				}
		return usage

	def _query(self, region: str, sql: str, key: str) -> list:
		source = frappe.get_cached_value("Region", region, "telemetry_data_source")
		if not source or "insights" not in frappe.get_installed_apps():
			self.gaps.append(region)
			return []

		cache_key = f"billing-telemetry:{key}:{hashlib.sha1(sql.encode()).hexdigest()[:12]}"
		if (cached := frappe.cache.get_value(cache_key)) is not None:
			return cached
		try:
			_, rows = frappe.get_doc("Region", region).run_telemetry_sql(sql)
		except Exception:
			frappe.log_error(title=f"Billing telemetry unavailable: {region}", message=frappe.get_traceback())
			self.gaps.append(region)
			return []
		frappe.cache.set_value(cache_key, rows, expires_in_sec=CACHE_SECONDS)
		return rows


def _by_region(records: list, id_field: str) -> dict[str, list[str]]:
	grouped = defaultdict(list)
	for record in records:
		value = record.get(id_field)
		if value and SAFE_ID.match(value):
			grouped[record.get("region")].append(value)
	return grouped


def _in_list(values: list[str]) -> str:
	return ", ".join(f"'{value}'" for value in values)


def _server_sql(names: list[str], days: int) -> str:
	return f"""
SELECT resource_id,
  avgIf(value, metric = 'system_cpu_usage_percent'),
  quantileIf(0.95)(value, metric = 'system_cpu_usage_percent'),
  avgIf(value, metric = 'system_memory_used_bytes') / {GIB},
  maxIf(value, metric = 'system_disk_used_bytes') / {GIB},
  avgIf(value, metric = 'system_network_transmit_bytes_per_second'),
  avgIf(value, metric = 'system_network_receive_bytes_per_second')
FROM samples
WHERE ts >= now() - INTERVAL {int(days)} DAY
  AND metric IN ({_in_list(list(SERVER_METRICS))})
  AND resource_id IN ({_in_list(names)})
GROUP BY resource_id
"""


def _host_sql(ids: list[str]) -> str:
	return f"""
SELECT resource_id,
  avgIf(value, metric = 'system_cpu_usage_percent'),
  avgIf(value, metric = 'system_memory_used_bytes') / {GIB},
  argMaxIf(value, ts, metric = 'metal_vm_allocated_cpu_millicores') / 1000,
  argMaxIf(value, ts, metric = 'metal_vm_allocated_memory_bytes') / {GIB},
  argMaxIf(value, ts, metric = 'metal_vm_allocated_disk_bytes') / {GIB}
FROM samples
WHERE ts >= now() - INTERVAL 1 DAY
  AND metric IN ({_in_list(list(HOST_METRICS))})
  AND resource_id IN ({_in_list(ids)})
GROUP BY resource_id
"""
