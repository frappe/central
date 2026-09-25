import frappe

from central.billing.ingester.connection import get, post, put
from central.billing.revenue import gst_status


def create_customer_profile(billing_profile):
	customer = create_customer(billing_profile)
	if customer:
		create_address(customer, billing_profile)
		create_contact(customer, billing_profile)
		billing_profile.db_set("profile_id", customer.name)
		gstin_details = get_gstin_details(billing_profile.gstin) if billing_profile.gstin else None
		if gstin_details:
			gst_status.store(billing_profile.team, billing_profile.gstin, gstin_details)
		build_tax_profile(billing_profile, gstin_details or {})


def create_customer(billing_profile):
	return post(
		endpoint="/api/resource/Customer",
		payload={"customer_name": billing_profile.legal_name, "gstin": billing_profile.gstin},
	)


def create_address(customer, billing_profile):
	address = post(
		endpoint="/api/resource/Address",
		payload={
			"address_title": customer.customer_name,
			"address_type": "Billing",
			"address_line1": billing_profile.address_line1,
			"address_line2": billing_profile.address_line2,
			"city": billing_profile.city,
			"state": billing_profile.state,
			"pincode": billing_profile.pincode,
			"country": billing_profile.country,
			"gstin": billing_profile.gstin,
			"is_primary_address": 1,
			"is_shipping_address": 1,
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
		},
	)
	return address.name


def create_contact(customer, billing_profile):
	user = frappe.db.get_value("User", billing_profile.team_owner, ["first_name", "last_name"], as_dict=True)
	email_ids = [{"email_id": billing_profile.team_owner, "is_primary": 1}]

	if billing_profile.team_owner != billing_profile.email:
		email_ids.append({"email_id": billing_profile.email})

	post(
		endpoint="/api/resource/Contact",
		payload={
			"first_name": user.first_name,
			"last_name": user.last_name,
			"is_primary_contact": 1,
			"email_ids": email_ids,
			"phone_nos": [{"phone": billing_profile.phone, "is_primary_phone": 1}],
			"links": [{"link_doctype": "Customer", "link_name": customer.name}],
		},
	)


def get_gstin_details(gstin):
	return get(
		"/api/method/india_compliance.gst_india.utils.gstin_info.get_gstin_info",
		payload={
			"gstin": gstin,
		},
	)


def build_tax_profile(billing_profile, gstin_details):
	from central.billing.payments.provisioning import ensure_tax_profile

	tax_profile = ensure_tax_profile(billing_profile.team)

	if gstin_details.get("gst_category") == "SEZ":
		tax_profile.zero_rated = 1
		tax_profile.zero_rating_reason = "SEZ"
		tax_profile.save(ignore_permissions=True)


### Update customer profile ###
def update_customer_profile(billing_profile):
	pass
