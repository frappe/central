import argparse
import json
import os
from pathlib import Path

import frappe

BENCH = Path(__file__).resolve().parents[5]


def main() -> None:
	parser = argparse.ArgumentParser(description="Seed a documentation demo site.")
	parser.add_argument("--site", default="docs.localhost")
	parser.add_argument("--overlay-only", action="store_true", help="Keep billing data and redo the overlay.")
	arguments = parser.parse_args()

	# Frappe writes its logs relative to the working directory, as a bench process does.
	os.chdir(BENCH / "sites")
	frappe.init(arguments.site, sites_path=".")
	frappe.connect()
	try:
		if not frappe.conf.get("docs_demo_site"):
			raise SystemExit(
				f"{arguments.site} is not a documentation demo site. Set docs_demo_site in its site config."
			)

		from seed import billing, overlay

		if not arguments.overlay_only:
			billing.seed()
		print(json.dumps(overlay.seed(), indent=2, default=str))
		frappe.db.commit()
	finally:
		frappe.destroy()


main()
