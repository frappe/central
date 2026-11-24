def column(label: str, fieldname: str, fieldtype: str, width: int, options: str | None = None) -> dict:
	spec = {"label": label, "fieldname": fieldname, "fieldtype": fieldtype, "width": width}
	if options:
		spec["options"] = options
	return spec
