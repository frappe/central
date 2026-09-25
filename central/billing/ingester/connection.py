import frappe
import requests

def _auth_headers() -> dict:
	key = frappe.conf.get("erpnext_api_key")
	secret = frappe.conf.get("erpnext_api_secret")
	if key and secret:
		return {"Authorization": f"token {key}:{secret}"}
	return {}

def validate_base_url():
	if not frappe.conf.get("erpnext_url"):
		frappe.log_error(message='ERPNext URL is not defined under under common site config')

def post(endpoint, payload):
	if not frappe.conf.get("enable_erpnext_sync"):
		return

	validate_base_url()

	response = requests.post(
		f'{frappe.conf.get("erpnext_url")}/{endpoint}',
		json=payload,
		headers=_auth_headers(),
		timeout=30
	)
	response.raise_for_status()
	return (response.json().get('data') or {})

def get(endpoint, payload):
	if not frappe.conf.get("enable_erpnext_sync"):
		return

	validate_base_url()

	response = requests.get(
		f'{frappe.conf.get("erpnext_url")}/{endpoint}',
		json=payload,
		headers=_auth_headers(),
		timeout=30
	)
	response.raise_for_status()
	return (response.json().get("data") or {})

def put(endpoint, payload):
	pass