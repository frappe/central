from frappe.model.document import Document


class SystemRecord(Document):
	"""A record that only Central writes after insert, from a region's report, a job, or a request
	it has authorized. Customers hold read access to it."""

	def reload_for_update(self) -> None:
		"""Read the latest values under the row lock, so a concurrent writer's change is not lost."""
		self.flags.for_update = True
		try:
			self.reload()
		finally:
			self.flags.for_update = False

	def save_as_system(self) -> None:
		"""Save a change Central makes. Links were checked at insert, and a record one points to can
		be gone by the time the change lands, which must not block it."""
		self.flags.ignore_links = True
		# Customers hold read access only; the caller authorized this change.
		self.save(ignore_permissions=True)
