# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

from frappe import _
from frappe.utils import cint, flt

from central.billing.report._columns import column
from central.billing.report._inventory import Inventory
from central.billing.report._telemetry import Telemetry


def execute(filters: dict | None = None):
	"""Who buys capacity they do not use, and who uses all of it: allocated against measured, per server.

	Only servers that run the Pilot agent report what they use; the rest are counted apart."""
	filters = filters or {}
	inventory = Inventory(filters)
	telemetry = Telemetry(days=cint(filters.get("days")) or 7)
	usage = telemetry.servers(inventory.servers)
	rows = [_row(server, usage[server.name]) for server in inventory.servers if server.name in usage]
	rows.sort(key=lambda row: row["unused_vcpus"], reverse=True)
	unmeasured = len(inventory.servers) - len(rows)
	return get_columns(), rows, _message(unmeasured, telemetry), _chart(rows), _summary(rows, unmeasured)


def _row(server, measured: dict) -> dict:
	used_vcpus = server.vcpus * measured["cpu_percent"] / 100
	peak_vcpus = server.vcpus * measured["cpu_peak_percent"] / 100
	return {
		"server": server.name,
		"title": server.title,
		"team": server.team,
		"team_name": server.team_name,
		"funding": _(server.funding),
		"vcpus": server.vcpus,
		"cpu_percent": measured["cpu_percent"],
		"cpu_peak_percent": measured["cpu_peak_percent"],
		"used_vcpus": flt(used_vcpus, 2),
		"unused_vcpus": flt(max(server.vcpus - peak_vcpus, 0), 2),
		"memory_gib": flt(server.memory_gib, 1),
		"memory_used_gib": measured["memory_used_gib"],
		"memory_used_percent": _percent(measured["memory_used_gib"], server.memory_gib),
		"disk_gib": server.disk_gib,
		"disk_used_gib": measured["disk_used_gib"],
		"disk_used_percent": _percent(measured["disk_used_gib"], server.disk_gib),
		"bandwidth_gib_month": measured["bandwidth_gib_month"],
	}


def _percent(part, whole) -> float:
	return flt(100 * flt(part) / flt(whole), 1) if flt(whole) else 0.0


def _message(unmeasured: int, telemetry: Telemetry) -> str:
	text = _(
		"Average and 95th percentile over the last {0} days. Unused vCPUs are those above the 95th percentile, so a server that peaks keeps its headroom."
	).format(telemetry.days)
	if unmeasured:
		text += " " + _("{0} live server(s) do not report usage (no Pilot agent) and are not listed.").format(
			unmeasured
		)
	if telemetry.gaps:
		text += " " + _("No telemetry for: {0}.").format(", ".join(sorted(set(telemetry.gaps))))
	return text


def _chart(rows: list[dict]) -> dict | None:
	top = rows[:15]
	if not top:
		return None
	return {
		"data": {
			"labels": [row["title"] or row["server"] for row in top],
			"datasets": [
				{"name": _("Used vCPUs"), "values": [row["used_vcpus"] for row in top]},
				{"name": _("Unused vCPUs"), "values": [row["unused_vcpus"] for row in top]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": 1},
	}


def _summary(rows: list[dict], unmeasured: int) -> list[dict]:
	allocated = sum(row["vcpus"] for row in rows)
	used = sum(row["used_vcpus"] for row in rows)
	return [
		{"label": _("Servers Measured"), "value": len(rows), "datatype": "Int"},
		{"label": _("Not Measured"), "value": unmeasured, "datatype": "Int", "indicator": "Orange"},
		{"label": _("Average CPU Used"), "value": f"{_percent(used, allocated)}%", "datatype": "Data"},
		{
			"label": _("Unused vCPUs"),
			"value": flt(sum(row["unused_vcpus"] for row in rows), 1),
			"datatype": "Float",
			"indicator": "Orange",
		},
	]


def get_columns() -> list[dict]:
	return [
		column(_("Server"), "server", "Link", 130, options="Virtual Machine"),
		column(_("Title"), "title", "Data", 140),
		column(_("Team Name"), "team_name", "Data", 150),
		column(_("Who Pays"), "funding", "Data", 130),
		column(_("vCPUs"), "vcpus", "Float", 70, precision=1),
		column(_("CPU Avg %"), "cpu_percent", "Percent", 90),
		column(_("CPU Peak %"), "cpu_peak_percent", "Percent", 90),
		column(_("Unused vCPUs"), "unused_vcpus", "Float", 110, precision=2),
		column(_("Memory (GiB)"), "memory_gib", "Float", 110, precision=1),
		column(_("Memory Used %"), "memory_used_percent", "Percent", 120),
		column(_("Disk (GiB)"), "disk_gib", "Float", 90, precision=0),
		column(_("Disk Used %"), "disk_used_percent", "Percent", 100),
		column(_("Bandwidth (GiB a Month)"), "bandwidth_gib_month", "Float", 160, precision=1),
	]
