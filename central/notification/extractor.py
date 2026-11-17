import json
from collections.abc import Iterator

from central.notification.engine import TRANSLATED_FIELDS


def extract(fileobj, *args, **kwargs) -> Iterator[tuple[None, str, str, list[str]]]:
	"""Yield the copy of each Notification Event Type in the fixture, for the translation catalog."""
	for event in json.load(fileobj):
		for field in TRANSLATED_FIELDS:
			if message := event.get(field):
				yield None, "_", message, [f"{field} of Notification Event Type {event['name']}"]
