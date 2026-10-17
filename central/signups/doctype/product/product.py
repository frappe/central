# Copyright (c) 2026, frappe and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.email.email_body import inline_style_in_html
from frappe.model.document import Document
from frappe.utils import add_days, escape_html, formatdate, get_url, nowdate

PRODUCT_KEY_PATTERN = re.compile(r"[a-z][a-z0-9-]*")
# Stands for Frappe Cloud itself where a product key is expected, such as in a Product Referral name.
FRAPPE_CLOUD_PRODUCT_KEY = "fc"
# A Frappe app's module name, which Cargo writes as the image's app tag.
# A path on the site itself, never another host.
LANDING_ROUTE_PATTERN = re.compile(r"/[A-Za-z0-9_/-]*")
APP_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
# The lifecycle emails a product can add a note to, as in Product Email Note.
PRODUCT_EMAILS = (
	"site_ready",
	"trial_unopened",
	"trial_expiring",
	"trial_ended",
	"trial_deletion_soon",
	"trial_converted",
)
# The emails that welcome a customer to a new site, which carry the getting started link.
GETTING_STARTED_EMAILS = ("site_ready", "trial_unopened")


class Product(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from central.signups.doctype.product_email_note.product_email_note import ProductEmailNote

		email_notes: DF.Table[ProductEmailNote]
		enabled: DF.Check
		getting_started_url: DF.Data | None
		landing_route: DF.Data | None
		logo: DF.AttachImage | None
		product_key: DF.Data
		signup_app: DF.Data
		subtitle: DF.SmallText | None
		title: DF.Data
		trial_days: DF.Int
		trial_deletion_days: DF.Int
		use_own_email_branding: DF.Check
	# end: auto-generated types

	def validate(self) -> None:
		if not PRODUCT_KEY_PATTERN.fullmatch(self.product_key or ""):
			frappe.throw(_("Use lowercase letters, numbers and hyphens for the product key."))

		if self.product_key == FRAPPE_CLOUD_PRODUCT_KEY:
			frappe.throw(_("The product key {0} is reserved.").format(FRAPPE_CLOUD_PRODUCT_KEY))

		if not self.is_new() and self.has_value_changed("product_key"):
			frappe.throw(_("The product key cannot change after creation."))

		if not APP_NAME_PATTERN.fullmatch(self.signup_app or ""):
			frappe.throw(_("Use the app's module name for the signup app, such as raven."))

		if self.landing_route and not LANDING_ROUTE_PATTERN.fullmatch(self.landing_route):
			frappe.throw(_("Use a path on the site for the landing route, such as /raven."))

		self.validate_emails()

	def validate_emails(self) -> None:
		"""An email client loads the logo without a session, so it must be a public file."""
		if self.use_own_email_branding and not (self.logo or "").startswith("/files/"):
			frappe.throw(_("Upload a public logo to use the product's branding in emails."))

		if self.getting_started_url and not self.getting_started_url.startswith("https://"):
			frappe.throw(_("Use an https:// address for the getting started page."))

		events = [row.event_type for row in self.email_notes]
		if len(events) != len(set(events)):
			frappe.throw(_("Add at most one note for each email."))

	def get_email_brand(self) -> dict | None:
		"""The logo and title for an email header, or None to keep Frappe Cloud's. Both are
		escaped, because a Product Operator writes them and Jinja does not escape."""
		if not self.use_own_email_branding:
			return None

		return {"title": escape_html(self.title), "logo_url": escape_html(get_url(self.logo))}

	def get_email_extras(self, event_type: str) -> dict:
		"""What an email about a site of this product adds: the branding, the note as escaped
		paragraphs, and the getting started link on a welcome email."""
		note = next((row.note for row in self.email_notes if row.event_type == event_type), "")
		url = self.getting_started_url if event_type in GETTING_STARTED_EMAILS else None

		return {
			"brand": self.get_email_brand(),
			"notes": [escape_html(part.strip()) for part in note.split("\n\n") if part.strip()],
			"getting_started_url": escape_html(url) if url else None,
		}

	@frappe.whitelist(methods=["POST"])
	def preview_email(self, event_type: str) -> dict:
		"""Operator action: the email as a customer sees it, with sample values and the form's
		unsaved changes. Needs write access to the product."""
		self.check_permission("write")
		self.validate_emails()
		if event_type == "signup_code":
			subject, html = self.render_code_email()
		else:
			subject, html = self.render_lifecycle_email(event_type)

		return {"subject": subject, "html": inline_style_in_html(html)}

	def render_code_email(self) -> tuple[str, str]:
		from central.users import get_code_email

		subject_for, heading, brand = get_code_email(self, is_new_user=True)
		# nosemgrep: frappe-ssti -- a fixed template that ships with the app, filled only with values.
		html = frappe.render_template(
			"templates/emails/verification_code.html",
			{"code": "123456", "heading": heading, "brand": brand, "expires_minutes": 10},
		)
		return subject_for("123456"), html

	def render_lifecycle_email(self, event_type: str) -> tuple[str, str]:
		from central.notification.engine import get_event_type, render_notification_email

		event = get_event_type(event_type) if event_type in PRODUCT_EMAILS else None
		if not event:
			frappe.throw(_("Choose one of the product's emails to preview."))

		context = self.get_preview_context()
		extras = self.get_email_extras(event_type)
		if event_type in GETTING_STARTED_EMAILS:
			extras["site_url"] = f"https://{context['context']['address']}{self.landing_route or ''}"

		return render_notification_email(event, context, extras)

	@frappe.whitelist(methods=["POST"])
	def send_test_email(self, event_type: str) -> None:
		"""Operator action: send the previewed email to the operator's own address."""
		email = self.preview_email(event_type)
		frappe.sendmail(
			recipients=[frappe.session.user],
			subject=_("[Test] {0}").format(email["subject"]),
			message=email["html"],
			now=True,
		)

	def get_preview_context(self) -> dict:
		address = (
			f"acme.{frappe.db.get_value('Region', {'status': 'Active'}, 'proxy_domain') or 'example.com'}"
		)
		return {
			"team": "",
			"team_name": _("Acme"),
			"reference_title": address,
			"message": "",
			"context": {
				"product": self.title,
				"address": address,
				"ends_on": formatdate(add_days(nowdate(), 3)),
				"deletes_on": formatdate(add_days(nowdate(), 17)),
				"days_left": 3,
			},
		}

	@frappe.whitelist(methods=["POST"])
	def preview_images(self, region: str, offset: int = 0) -> dict:
		"""1. Require a System Manager, because the preview reads the region as the system tenant."""
		from central.integrations.images import preview_images
		from central.site_provisioning import product_image_tags, signup_offering

		frappe.only_for("System Manager")

		return preview_images(
			signup_offering(), region, offset, extra_tags=product_image_tags(self.signup_app)
		)


def get_email_product(product_key: str | None) -> Product | None:
	"""The product whose branding and notes an email uses, or None for Frappe Cloud's own."""
	if not product_key or not frappe.db.exists("Product", product_key):
		return None

	return frappe.get_cached_doc("Product", product_key)


def get_enabled_product_key(product_key: str | None) -> str | None:
	"""The stored key of an enabled product, or None. The database matches a key in any case."""
	return (
		frappe.db.get_value("Product", {"name": product_key, "enabled": 1}, "name") if product_key else None
	)


def get_signup_product(product_key: str) -> Product:
	"""The enabled product a signup names, or a refusal the customer can read."""
	if not frappe.db.exists("Product", {"name": product_key, "enabled": 1}):
		frappe.throw(_("This product is not available for signup."))

	return frappe.get_cached_doc("Product", product_key)
