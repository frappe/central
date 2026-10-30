# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt


def column(label: str, fieldname: str, fieldtype: str, width: int = 110, **extra) -> dict:
	"""One report column. An INR money column passes options="inr", which every row carries."""
	return {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **extra}


def inr(label: str, fieldname: str, width: int = 120) -> dict:
	return column(label, fieldname, "Currency", width, options="inr")
