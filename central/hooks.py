app_name = "central"
app_title = "Central"
app_publisher = "frappe"
app_description = "The one stop console for Frappe Cloud"
app_email = "prathamesh@frappe.io"
app_license = "agpl-3.0"

fixtures = [
	"Capability",
	# The trust-tier ladder (Beginner → Elite) with per-currency spend caps and
	# promotion thresholds — reference data every team's caps resolve against.
	"Trust Tier Level",
	{"dt": "Team Role", "filters": [["is_system", "=", 1]]},
	{"dt": "Role", "filters": [["name", "in", ["Central User"]]]},
]

# The TypeScript UI owns the product route.
website_route_rules = [
	{"from_route": "/dashboard/<path:app_path>", "to_route": "dashboard"},
]

# Central is a website application. Portal users land in the console; Desk stays
# reserved for users whose roles explicitly grant desk access.
website_user_home_page = "dashboard"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "central",
# 		"logo": "/assets/central/logo.png",
# 		"title": "Central",
# 		"route": "/central",
# 		"has_permission": "central.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/central/css/central.css"
# app_include_js = "/assets/central/js/central.js"

# include js, css files in header of web template
# web_include_css = "/assets/central/css/central.css"
# web_include_js = "/assets/central/js/central.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "central/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "central/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "central.utils.jinja_methods",
# 	"filters": "central.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "central.install.before_install"
# Seed the catalog taxonomy masters (Plan Category / Sub-Category / Resource Type) on a
# fresh install — patches are skipped on fresh installs, so the seed can't live only
# there. Idempotent (ADR 0007).
#
# `ensure_constraints` is here for exactly the same reason: a CHECK constraint declared
# only in a patch would exist on migrated sites and be silently ABSENT on fresh ones.
# The money invariants are a property of the schema, not of a site's history (ADR 0018).
after_install = [
	"central.billing.catalog.taxonomy_setup.ensure_catalog_masters",
	"central.billing.platform.constraints.ensure_constraints",
	"central.billing.settings.ensure_welcome_credit_amounts",
]

# Uninstallation
# ------------

# before_uninstall = "central.uninstall.before_uninstall"
# after_uninstall = "central.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "central.utils.before_app_install"
# after_app_install = "central.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "central.utils.before_app_uninstall"
# after_app_uninstall = "central.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "central.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "central.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"User": {
		"after_insert": "central.users.bootstrap_user_team",
	},
	"Team": {
		# Keep a staging-trial team's billing profile complete so it can create servers
		# without the setup prompt (the profile gate is otherwise enforced in the console).
		"on_update": "central.billing.payments.provisioning.on_team_update",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		# Asset mirror: reconcile against every Active Atlas every 10 minutes — the
		# backstop that corrects drift the event push (central.api.atlas.event) missed.
		"*/10 * * * *": ["central.integrations.atlas.reconcile"],
		# Billing: the monthly run. Drafting fires once, on the 1st, and fans the
		# just-closed month out as one page job per team. Collection is NOT a second
		# tick a fixed few hours later — at scale drafting may still be running then,
		# and a one-shot scan would collect only what existed at that instant and
		# orphan the rest. It is a daily sweep instead (see the `daily` list below):
		# `collect_due_invoices` drains every Draft whose month has closed, re-running
		# until nothing is owed. Rating is heavy and local, collection slow and
		# external, so they stay separate ticks.
		"0 1 1 * *": ["central.billing.revenue.invoicing.draft_monthly_invoices"],
	},
	"daily": [
		"central.central.doctype.team_invitation.team_invitation.expire_pending_invitations",
		# Billing: collect the monthly run. A daily sweep of every Draft whose month
		# has closed (period_end <= the just-closed month), fanned out as page jobs.
		# Re-runs harmlessly: a settled draft drops out of the scan, so once the run
		# has drained this is a cheap indexed no-op. Runs before dunning so a fresh
		# charge is attempted before any retry ladder is considered.
		"central.billing.revenue.invoicing.collect_due_invoices",
		# Billing (module): retry/dunning + staged suspension for unpaid invoices,
		# and pruning Payment Attempt / Webhook Event logs.
		"central.billing.revenue.dunning.run_dunning",
		"central.billing.payments.charges.cleanup_payment_logs",
		# E-mandate (INR ≤₹15k): send the pre-debit notice, then debit after 24h.
		"central.billing.payments.emandate.run_emandate_cycle",
		# Backfill Subscriptions for any Running Asset missing an active one.
		"central.billing.catalog.subscriptions.backfill_missing_subscriptions",
		# Services (LLM): refresh the model catalog from the Grove backend.
		"central.services.llm.sync_models",
		# Assert the money invariants that no DB constraint can hold (they span
		# tables): wallet == its ledger, invoice == its lines, captured == amount_paid.
		# Silence is the success case; a violation is logged with its team and amount.
		# Read it as the "Billing Invariant Violations" report.
		"central.billing.platform.invariants.run_invariant_audit",
	],
	"hourly": [
		# Billing: ERPNext sync retries whose backoff window has elapsed.
		"central.billing.revenue.erpnext_sync.retry_failed_syncs",
		# Services (LLM): reconcile Grove's cumulative token usage into billing.
		"central.services.llm.pull_usage",
		# A charge whose outcome we don't know is money in the air: ask the gateway and
		# settle it. It waits 30 minutes for the webhook first, so a daily sweep left it
		# hanging for up to a day — and the key it needs to re-send safely expires in
		# about one (ADR 0017).
		"central.billing.payments.reconciliation.run_reconciliation",
		# The sweeps above detect what they cannot fix; this is what pages a human
		# about it — unresolved invariants, failed webhooks, attempts still in flight.
		"central.billing.platform.alerts.run_operator_alerts",
	],
	"monthly": [
		# Billing: cards expire at the end of their printed month; flip lapsed ones.
		"central.billing.payments.payments.expire_payment_methods",
	],
}

# Billing (module): authorisation is Central's capability IAM (ADR 0004) — no
# billing-owned roles or User->team field to provision. The catalog taxonomy masters,
# however, are reference data the catalog can't run without, so re-assert them on every
# migrate too (idempotent — ADR 0007). The money CHECK constraints are re-asserted for
# the same reason: a dropped or never-applied constraint must heal on migrate, not wait
# for someone to notice the balance went negative (ADR 0018).
after_migrate = [
	"central.billing.catalog.taxonomy_setup.ensure_catalog_masters",
	"central.billing.platform.constraints.ensure_constraints",
	# The per-currency welcome grant can't be a field default (it's a child table),
	# so it is seeded here — once, on a Billing Settings nobody has saved yet.
	"central.billing.settings.ensure_welcome_credit_amounts",
]

# Testing
# -------

# Tests run on a fresh site (patches skipped), so seed the taxonomy masters the test
# fixtures depend on — and apply the money constraints — before the suite runs.
before_tests = [
	"central.billing.catalog.taxonomy_setup.ensure_catalog_masters",
	"central.billing.platform.constraints.ensure_constraints",
	"central.billing.settings.ensure_welcome_credit_amounts",
]

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "central.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "central.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "central.task.get_dashboard_data"
# }
override_doctype_dashboards = {
	"Currency": "central.billing.api.dashboard_overrides.currency_dashboard",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# TODO: This needs to be removed once we have a first-class claim hook in Frappe framework.
before_request = ["central.oauth.install_oauth_claim_patch"]
# after_request = ["central.utils.after_request"]

# Job Events
# ----------
# before_job = ["central.utils.before_job"]
# after_job = ["central.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization

permission_query_conditions = {
	"Asset": "central.permissions.asset_query_conditions",
	"IAM Permission Probe": "central.permissions.iam_permission_probe_query_conditions",
	"Site": "central.permissions.site_query_conditions",
	"Team": "central.permissions.team_query_conditions",
	"Team Invitation": "central.permissions.team_invitation_query_conditions",
	"Team Role": "central.permissions.team_role_query_conditions",
}

has_permission = {
	"Asset": "central.permissions.asset_has_permission",
	"IAM Permission Probe": "central.permissions.iam_permission_probe_has_permission",
	"Site": "central.permissions.site_has_permission",
	"Team": "central.permissions.team_has_permission",
	"Team Invitation": "central.permissions.team_invitation_has_permission",
	"Team Role": "central.permissions.team_role_has_permission",
}

override_whitelisted_methods = {
	"frappe.integrations.oauth2.openid_profile": "central.oauth.openid_profile",
}
# --------------------------------

# auth_hooks = [
# 	"central.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
