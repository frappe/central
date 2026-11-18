import frappe
from frappe.tests import IntegrationTestCase

# The DPA (Schedule II, rows 2 and 13) promises a version log on every critical document.
CRITICAL_DOCTYPES = (
	"AI Settings",
	"AI Trial Key",
	"Billing Profile",
	"Capability",
	"Central Settings",
	"Central SSO Settings",
	"Credit Ledger Entry",
	"Credit Wallet",
	"Email OAuth Provider",
	"FrappeMail Service",
	"Gateway Customer",
	"GitHub Connection",
	"Invoice",
	"Metal Server",
	"Metal VPN Profile",
	"Payment Attempt",
	"Payment Method",
	"Pilot Credential",
	"Refund",
	"Region",
	"Resource Action",
	"Service Detail",
	"Site",
	"Site Domain",
	"Subscription",
	"Tax Profile",
	"Team",
	"Team Invitation",
	"Team Role",
	"Team Service",
	"Team SSH Key",
	"Top-up Order",
	"User Mail Account",
	"User Notification Preference",
	"Virtual Machine",
	"VM Snapshot",
	"Warpgate Access",
	"WireGuard Device",
)


class TestTrackChanges(IntegrationTestCase):
	def test_every_dpa_critical_doctype_has_track_changes_enabled(self):
		untracked = [doctype for doctype in CRITICAL_DOCTYPES if not frappe.get_meta(doctype).track_changes]
		self.assertEqual(untracked, [])
