import frappe


def execute() -> None:
	"""Use the full Ubuntu image for raw servers, preserving other offering settings."""
	if not frappe.db.exists("Image Offering", "ubuntu"):
		return

	offering = frappe.get_doc("Image Offering", "ubuntu")
	for tag in offering.required_tags:
		if tag.key == "minimal":
			if tag.value != "false":
				tag.value = "false"
				offering.save()
			return

	offering.append("required_tags", {"key": "minimal", "value": "false"})
	offering.save()
