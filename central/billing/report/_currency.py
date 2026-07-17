# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Shared helper: split money columns per currency in a cross-team report.

A report that lists rows across teams mixes currencies. A single money column
(with a separate Currency column) then can't be read or totalled — ₹16,980 and
$200 stacked in one column misread, and any column total is a false number in no
currency at all. `split_currency_columns` replaces each money column with one
column per currency actually present (Total (INR), Total (USD), …) so each
currency stands on its own. It only splits when two or more currencies appear —
a single-currency run keeps the plainer layout.
"""


def split_currency_columns(columns, rows, money_fields, currency_field="currency"):
	"""Return columns with each `money_fields` column split into one column per
	currency present in `rows`; mutate `rows` to populate the split fields. The
	standalone `currency_field` column is dropped (each split column names its
	currency). A run with fewer than two currencies is returned unchanged."""
	currencies = sorted({(r.get(currency_field) or "").strip() for r in rows if r.get(currency_field)})
	if len(currencies) < 2:
		return columns

	money = set(money_fields)
	new_columns = []
	for col in columns:
		fieldname = col.get("fieldname")
		if fieldname == currency_field:
			continue  # currency now lives in each split column's header
		if fieldname in money:
			for currency in currencies:
				new_columns.append({
					"label": f"{col['label']} ({currency})",
					"fieldname": f"{fieldname}_{currency.lower()}",
					"fieldtype": "Currency",
					"options": currency,
					"width": col.get("width", 120),
				})
		else:
			new_columns.append(col)

	for row in rows:
		currency = (row.get(currency_field) or "").strip()
		if not currency:
			continue
		for fieldname in money:
			value = row.get(fieldname)
			if value is not None:
				row[f"{fieldname}_{currency.lower()}"] = value
	return new_columns
