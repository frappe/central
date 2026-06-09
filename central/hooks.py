app_name = "central"
app_title = "Central"
app_publisher = "frappe"
app_description = "The one stop console for Frappe Cloud"
app_email = "prathamesh@frappe.io"
app_license = "agpl-3.0"

fixtures = [
	"Capability",
	{"dt": "Team Role", "filters": [["is_system", "=", 1]]},
	{"dt": "Role", "filters": [["name", "in", ["Central User"]]]},
]

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
# after_install = "central.install.after_install"

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
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"central.central.doctype.team_invitation.team_invitation.expire_pending_invitations",
		# Billing (module): retry/dunning + staged suspension for unpaid invoices,
		# gateway reconciliation, and pruning Payment Attempt / Webhook Event logs.
		"central.billing.revenue.dunning.run_dunning",
		"central.billing.payments.reconciliation.run_reconciliation",
		"central.billing.payments.charges.cleanup_payment_logs",
	],
	"hourly": [
		# Billing: ERPNext sync retries whose backoff window has elapsed.
		"central.billing.revenue.erpnext_sync.retry_failed_syncs",
	],
	"monthly": [
		# Billing: cards expire at the end of their printed month; flip lapsed ones.
		"central.billing.payments.payments.expire_payment_methods",
	],
}

# Billing (module): ensure roles + the User->team link field exist after migrate.
# Transitional compat shim — retired by issues #42/#43.
after_migrate = [
	"central.billing.platform.security.ensure_billing_roles",
	"central.billing.api.dashboard.ensure_billing_team_field",
]

# Testing
# -------

# before_tests = "central.install.before_tests"

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
	"Team": "central.permissions.team_query_conditions",
	"Team Invitation": "central.permissions.team_invitation_query_conditions",
	"Team Role": "central.permissions.team_role_query_conditions",
}

has_permission = {
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
