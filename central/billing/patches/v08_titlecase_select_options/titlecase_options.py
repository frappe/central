# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Title-case stored Select option values to match the new field options.

Every billing Select field's options moved from lower/snake_case to Title Case
(e.g. account_standing "past_due" -> "Past Due"). Existing rows still hold the
old values, so rewrite them in place. Runs post_model_sync, after the DocType
schema (and its option list) has been migrated. Idempotent: each update only
touches rows still holding an old value.

Gateway-protocol strings (Stripe/Razorpay/PayPal API casing) are NOT stored in
these fields and are deliberately untouched.
"""

import frappe

# {DocType: {fieldname: {old_value: new_value}}}
RENAMES = {
	"Add-on": {
		"resource_type": {"compute": "Compute", "memory": "Memory", "disk": "Disk", "transfer": "Transfer", "ip": "IP", "snapshot": "Snapshot"},
		"billing_type": {"fixed": "Fixed", "metered": "Metered"},
		"pricing_mode": {"grandfathered": "Grandfathered", "live": "Live"},
		"billing_interval": {"hourly": "Hourly", "daily": "Daily", "monthly": "Monthly"},
	},
	"Billing Notification Log": {
		"event_type": {
			"payment_success": "Payment Success", "payment_failure": "Payment Failure",
			"payment_retry": "Payment Retry", "invoice_overdue": "Invoice Overdue",
			"credit_low": "Credit Low", "card_expiry": "Card Expiry",
			"mandate_reauth": "Mandate Reauth", "trial_expiring": "Trial Expiring",
		},
		"status": {"sent": "Sent", "suppressed": "Suppressed"},
	},
	"Billing Profile": {
		"billing_mode": {"postpaid": "Postpaid", "prepaid": "Prepaid"},
	},
	"Credit Ledger Entry": {
		"entry_type": {"credit": "Credit", "debit": "Debit"},
	},
	"Invoice": {
		"invoice_type": {"billable": "Billable", "cost_report": "Cost Report"},
		"output_tax_type": {"none": "None"},
		"zero_rating_reason": {"sez_lut": "SEZ LUT", "export": "Export"},
		"erpnext_sync_status": {"pending": "Pending", "synced": "Synced", "failed": "Failed"},
	},
	"Payment Attempt": {
		"status": {"initiated": "Initiated", "authorised": "Authorised", "captured": "Captured", "failed": "Failed", "refunded": "Refunded"},
		"resolved_by": {"webhook": "Webhook", "reconciliation": "Reconciliation"},
	},
	"Payment Gateway": {
		"adapter_key": {"stripe": "Stripe", "razorpay": "Razorpay", "paypal": "Paypal"},
	},
	"Payment Method": {
		"method_type": {"card": "Card", "upi_autopay": "UPI Autopay", "prepaid_credits": "Prepaid Credits"},
		"status": {"pending_validation": "Pending Validation", "active": "Active", "paused": "Paused", "cancelled": "Cancelled", "expired": "Expired", "failed": "Failed"},
	},
	"Plan": {
		"billing_cycle": {"monthly": "Monthly", "annual": "Annual"},
	},
	"Plan Includes": {
		"resource_type": {"compute": "Compute", "memory": "Memory", "disk": "Disk", "transfer": "Transfer", "ip": "IP", "snapshot": "Snapshot"},
	},
	"Refund": {
		"destination": {"source": "Source", "wallet": "Wallet"},
		"status": {"initiated": "Initiated", "completed": "Completed", "failed": "Failed"},
	},
	"Subscription": {
		"billing_cycle": {"monthly": "Monthly", "annual": "Annual"},
		"account_standing": {"current": "Current", "past_due": "Past Due", "suspended": "Suspended"},
	},
	"Subscription Change": {
		"change_type": {
			"created": "Created", "plan_changed": "Plan Changed",
			"payment_method_changed": "Payment Method Changed", "past_due": "Past Due",
			"suspended": "Suspended", "reactivated": "Reactivated", "cancelled": "Cancelled",
		},
	},
	"Tax Profile": {
		"output_tax_type": {"none": "None"},
		"zero_rating_reason": {"sez_lut": "SEZ LUT", "export": "Export"},
	},
	"Usage Rollup": {
		"meter_type": {"counter": "Counter", "gauge": "Gauge"},
	},
	"Webhook Event": {
		"status": {"received": "Received", "processed": "Processed", "failed": "Failed", "ignored": "Ignored"},
	},
}


def execute():
	for doctype, fields in RENAMES.items():
		if not frappe.db.table_exists(doctype):
			continue
		t = frappe.qb.DocType(doctype)
		for field, value_map in fields.items():
			if not frappe.db.has_column(doctype, field):
				continue
			column = getattr(t, field)
			for old, new in value_map.items():
				frappe.qb.update(t).set(column, new).where(column == old).run()
