from central.central.doctype.activity_event.backfill import backfill


def execute() -> None:
	"""Fill the activity feed with the history the site already recorded, up to its retention."""
	backfill()
