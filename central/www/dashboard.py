from __future__ import annotations

import json

import frappe

no_cache = 1

MANIFEST = "central/public/dashboard/.vite/manifest.json"
ASSET_BASE = "/assets/central/dashboard/"


def get_context(context):
	"""Inject the Vite-built SPA assets for the Central console.

	Reads the production manifest so the hashed entry chunk + its CSS load
	correctly behind the `/dashboard/<path>` route. During local development the
	SPA is served by `yarn dev`; production builds with `yarn build`.
	"""
	context.no_cache = 1
	context.css_files = []
	context.js_files = []

	manifest_path = frappe.get_app_path("central", "public", "dashboard", ".vite", "manifest.json")
	try:
		with open(manifest_path) as f:
			manifest = json.load(f)
	except FileNotFoundError:
		# Build not run yet — page renders an empty shell rather than erroring.
		return context

	entry = manifest.get("src/main.js") or manifest.get("index.html")
	if not entry:
		return context

	context.js_files = [ASSET_BASE + entry["file"]]
	context.css_files = [ASSET_BASE + css for css in entry.get("css", [])]
	return context
