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

from central.billing.api.dashboard.account import (
	get_billing_geo,
	get_billing_profile,
	get_billing_settings,
	get_collection_status,
	get_team_overview,
	get_trust_tier,
	list_switchable_teams,
	save_billing_profile,
	save_billing_settings,
	set_collection_mode,
	whoami,
)
from central.billing.api.dashboard.catalog import (
	get_eligible_plans,
)
from central.billing.api.dashboard.invoices import (
	confirm_invoice_checkout,
	confirm_topup,
	create_topup_order,
	credit_ledger,
	get_credit_balance,
	get_fallback_offer,
	get_forecast,
	get_invoice,
	get_topup_options,
	list_invoices,
	list_payment_attempts,
	list_subscriptions,
	pause_subscription,
	pay_invoice,
	pay_invoice_checkout,
	resume_subscription,
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
from central.billing.api.dashboard.outlook import (
	get_next_payment,
	get_payment_schedule,
)
from central.billing.api.dashboard.reports import (
	export_csv,
	get_spend_history,
	get_statement,
	get_tax_summary,
	list_refunds,
)
from central.billing.api.dashboard.services import (
	get_metered_services,
	subscribe_metered_service,
)
from central.billing.api.dashboard.spend import (
	get_cycle_costs,
	get_locked_prices,
)

__all__ = [
	"add_demo_card",
	"confirm_card",
	"confirm_invoice_checkout",
	"confirm_payment_method_order",
	"confirm_topup",
	"create_topup_order",
	"credit_ledger",
	"export_csv",
	"get_billing_geo",
	"get_billing_profile",
	"get_billing_settings",
	"get_collection_status",
	"get_credit_balance",
	"get_cycle_costs",
	"get_eligible_plans",
	"get_fallback_offer",
	"get_forecast",
	"get_invoice",
	"get_locked_prices",
	"get_metered_services",
	"get_next_payment",
	"get_payment_method_options",
	"get_payment_schedule",
	"get_spend_history",
	"get_statement",
	"get_tax_summary",
	"get_team_overview",
	"get_topup_options",
	"get_trust_tier",
	"initiate_card_setup",
	"list_invoices",
	"list_payment_attempts",
	"list_payment_methods",
	"list_refunds",
	"list_subscriptions",
	"list_switchable_teams",
	"pause_subscription",
	"pay_invoice",
	"pay_invoice_checkout",
	"remove_payment_method",
	"reorder_payment_methods",
	"resume_subscription",
	"save_billing_profile",
	"save_billing_settings",
	"set_collection_mode",
	"set_default_payment_method",
	"setup_payment_method_order",
	"subscribe_metered_service",
	"whoami",
]
