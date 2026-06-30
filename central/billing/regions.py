# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Region display metadata.

An Atlas Instance is named by its region slug only (autoname `field:region`), so
the slug — `ap-south-1`, `in-mumbai`, `blr` — is all we structurally carry. This
map turns a slug into the human label the subscription list shows
("Mumbai, India (AWS)"). Unknown slugs fall back to a title-cased slug rather than
erroring, so a newly-registered region still renders something sensible.
"""

# slug -> (city, country, provider)
REGION_META = {
	"ap-south-1": ("Mumbai", "India", "AWS"),
	"in-mumbai": ("Mumbai", "India", "AWS"),
	"mumbai": ("Mumbai", "India", "AWS"),
	"blr": ("Bengaluru", "India", "AWS"),
	"in-bengaluru": ("Bengaluru", "India", "AWS"),
	"us-east-1": ("N. Virginia", "USA", "AWS"),
	"eu-central-1": ("Frankfurt", "Germany", "AWS"),
	"eu-frankfurt": ("Frankfurt", "Germany", "Hetzner"),
	"me-dubai": ("Dubai", "UAE", "AWS"),
}


def region_label(slug: str | None) -> str | None:
	"""'Mumbai, India (AWS)' for a known region slug; a title-cased fallback
	('us-west-2' -> 'Us West 2') for an unknown one; None for an empty slug."""
	slug = (slug or "").strip()
	if not slug:
		return None
	meta = REGION_META.get(slug.lower())
	if not meta:
		return slug.replace("-", " ").replace("_", " ").title()
	city, country, provider = meta
	label = city
	if country:
		label += f", {country}"
	if provider:
		label += f" ({provider})"
	return label
