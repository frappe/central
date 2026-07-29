// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Billing Invariant Violations"] = {
	filters: [
		{
			fieldname: "check",
			label: __("Invariant"),
			fieldtype: "Select",
			options: [
				{ value: "", label: __("All") },
				{ value: "C2", label: __("C2 — Wallet balance equals its ledger") },
				{ value: "C4", label: __("C4 — Ledger running_balance chain is unbroken") },
				{ value: "I1", label: __("I1 — Invoice subtotal equals its line items") },
				{ value: "I5", label: __("I5 — Paid invoice is covered by card + credits") },
				{ value: "I6", label: __("I6 — One live invoice per team per period") },
				{ value: "P2", label: __("P2 — Captured payments equal invoice amount_paid") },
				{ value: "P4", label: __("P4 — No payment attempt left non-terminal") },
			],
		},
		{
			fieldname: "team",
			label: __("Team"),
			fieldtype: "Link",
			options: "Team",
		},
	],
};
