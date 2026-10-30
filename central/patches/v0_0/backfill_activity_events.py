from central.activity.backfill import backfill_server_events


def execute() -> None:
	"""Rebuild the feed from the records Central already keeps, within the retention window."""
	backfill_server_events()
