import frappe
from central.billing.ingester.connection import post, get, put

def create_customer_profile(billing_profile):
	customer = create_customer(billing_profile) 
	if customer:
		create_address(customer, billing_profile)
		create_contact(customer, billing_profile)

	billing_profile.db_set('profile_id', customer.name)

def create_customer(billing_profile):
	return post(
		endpoint='/api/resource/Customer', 
		payload={
			"customer_name": billing_profile.legal_name,
			"gstin": billing_profile.gstin
		}
	)

def create_address(customer, billing_profile):
	post(
		endpoint = '/api/resource/Address',
		payload = {
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
			"links":[
				{ "link_doctype": "Customer", "link_name": customer.name }
			]
		}
	)

def create_contact(customer, billing_profile):
	user = frappe.db.get_value(
		"User", billing_profile.team_owner, ['first_name', 'last_name'],as_dict=True
	)
	email_ids = [
		{ "email_id": billing_profile.team_owner, "is_primary": 1 }
	]

	if billing_profile.team_owner != billing_profile.email:
		email_ids.append(
			{ "email_id":billing_profile.email }
		)

	post(
		endpoint = '/api/resource/Contact',
		payload={
			"first_name": user.first_name,
			"last_name": user.last_name,
			"is_primary_contact": 1,
			"email_ids": email_ids,
			"phone_nos": [
				{ "phone": billing_profile.phone, "is_primary_phone": 1 }
			],
			"links": [
				{ "link_doctype": "Customer", "link_name": customer.name }
			]
		}
	)

### Update customer profile ###
def update_customer_profile(billing_profile):
	pass
