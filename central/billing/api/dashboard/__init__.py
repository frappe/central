# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Customer dashboard endpoints (issues #26, #18).

Every endpoint is auto-scoped to the caller's team via Central's capability IAM
(ADR 0004): reads require `billing:view`, mutations `billing:manage`. A member
without the capability — including the cluster Agent key — is rejected, and
passing another team's name is never silently widened. Cross-team admin data
lives on the admin dashboard (#19) behind the operator (System Manager) bypass.

Split into domain modules (account / invoices / methods) with shared helpers;
this package re-exports the public API so every `billing.api.dashboard.*` path
stays stable.
"""

from central.billing.api.dashboard.catalog import (
	get_eligible_plans,
)
from central.billing.api.dashboard.account import (
	get_billing_geo,
	get_billing_profile,
	get_billing_settings,
	get_collection_status,
	get_notification_preferences,
	get_team_overview,
	get_trust_tier,
	list_notifications,
	list_switchable_teams,
	save_billing_profile,
	save_billing_settings,
	save_notification_preferences,
	set_collection_mode,
	whoami,
)
from central.billing.api.dashboard.invoices import (
	confirm_topup,
	create_topup_order,
	credit_ledger,
	get_credit_balance,
	get_forecast,
	get_invoice,
	list_invoices,
	list_payment_attempts,
	confirm_invoice_checkout,
	list_subscriptions,
	pay_invoice,
	pay_invoice_checkout,
	purchase_credits,
)
from central.billing.api.dashboard.methods import (
	add_demo_card,
	confirm_card,
	confirm_payment_method_order,
	get_payment_method_options,
	initiate_card_setup,
	list_payment_methods,
	remove_payment_method,
	reorder_payment_methods,
	set_default_payment_method,
	setup_payment_method_order,
)

__all__ = [
	"whoami", "get_billing_profile", "get_billing_geo", "save_billing_profile", "get_billing_settings",
	"save_billing_settings", "get_team_overview", "get_trust_tier",
	"get_collection_status", "set_collection_mode",
	"list_switchable_teams",
	"list_notifications", "get_notification_preferences", "save_notification_preferences",
	"get_eligible_plans",
	"get_forecast", "list_subscriptions", "list_invoices", "get_invoice", "list_payment_attempts",
	"get_credit_balance", "credit_ledger", "purchase_credits", "pay_invoice", "create_topup_order",
	"confirm_topup", "pay_invoice_checkout", "confirm_invoice_checkout",
	"list_payment_methods", "get_payment_method_options", "initiate_card_setup", "confirm_card",
	"add_demo_card", "setup_payment_method_order", "confirm_payment_method_order",
	"remove_payment_method", "set_default_payment_method", "reorder_payment_methods",
]
