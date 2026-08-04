# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Postpaid, in-arrears invoice generation (issue #09).

Two phases, decoupled to avoid the 1st-of-month bottleneck:

  Phase 1 (28th, heavy/off-peak): per active subscription, reconcile sync if
    stale, compute day-weighted line items from Subscription Change segments
    (each Created/Plan Changed row opens a segment at its locked_rate snapshot,
    running until the next change, with the max(1, end-start) floor), and
    create a `Draft`.

  Phase 2 (1st, light/parallel): one job per draft applies credits, claims the
    `Draft -> Open` transition atomically (no invoice processed twice), and
    leaves collection to the charge step (#10).

Subscription Change already encodes both the time windows (effective_at per
row) and the rate snapshot, so billing reads only Central — no live Agent call
in the common (push-primary) case.

Split into modules (lines / generate / lifecycle / run); this package re-exports
the public API so callers and the `billing.revenue.invoicing.*` enqueue paths hold.
"""

from central.billing.revenue.invoicing.generate import (
	generate_draft_invoice,
	generate_team_invoice,
	reconcile_subscription,
)
from central.billing.revenue.invoicing.lifecycle import (
	cancel_invoice,
	open_and_collect,
	reissue_invoice,
)
from central.billing.revenue.invoicing.lines import compute_line_items, team_line_items
from central.billing.revenue.invoicing.run import (
	billing_run_status,
	collect_due_invoices,
	draft_monthly_invoices,
	draft_team_invoice,
	draft_team_page,
	generate_draft_invoices,
	open_drafts,
	run_monthly_billing,
	settle_draft,
	settle_draft_page,
)

__all__ = [
	"compute_line_items", "team_line_items",
	"reconcile_subscription", "generate_draft_invoice", "generate_team_invoice",
	"generate_draft_invoices", "draft_team_invoice", "draft_team_page",
	"open_and_collect", "open_drafts", "cancel_invoice", "reissue_invoice",
	"settle_draft", "settle_draft_page",
	"draft_monthly_invoices", "collect_due_invoices", "run_monthly_billing",
	"billing_run_status",
]
