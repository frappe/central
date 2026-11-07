import json
import sys
from collections.abc import Callable, Sequence
from typing import Any, TextIO

Getter = str | Callable[[dict], Any]
Column = tuple[str, Getter]


class Output:
	"""Prints results as aligned text for people, or as JSON for scripts and agents."""

	def __init__(self, is_json: bool = False, stream: TextIO | None = None) -> None:
		self.is_json = is_json
		self.stream = stream or sys.stdout

	def table(self, rows: Sequence[dict], columns: Sequence[Column], empty: str = "Nothing to show.") -> None:
		if self.is_json:
			return self.json(rows)
		if not rows:
			return self.line(empty)

		cells = [[header.upper() for header, _ in columns]]
		cells += [[format_value(read(row, getter)) for _, getter in columns] for row in rows]
		for line in align(cells):
			self.line(line)

	def record(self, record: dict, fields: Sequence[Column] | None = None) -> None:
		if self.is_json:
			return self.json(record)

		fields = fields or [(key, key) for key in record]
		width = max(len(label) for label, _ in fields)
		for label, getter in fields:
			self.line(f"{label.ljust(width)}  {format_value(read(record, getter))}")

	def result(self, data: Any, text: str) -> None:
		"""The raw result for JSON, else one line of text."""
		if self.is_json:
			return self.json(data)
		self.line(text)

	def json(self, data: Any) -> None:
		self.line(json.dumps(data, indent=2, default=str))

	def line(self, text: str = "") -> None:
		print(text, file=self.stream)


def align(cells: list[list[str]]) -> list[str]:
	"""Pad each column to its widest cell."""
	widths = [max(len(cell) for cell in column) for column in zip(*cells, strict=True)]
	return [
		"  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
		for row in cells
	]


def read(row: dict, getter: Getter) -> Any:
	return getter(row) if callable(getter) else row.get(getter)


def format_value(value: Any) -> str:
	if value is None or value == "":
		return "-"
	if isinstance(value, bool):
		return "yes" if value else "no"
	if isinstance(value, (list, tuple)):
		return ", ".join(format_value(item) for item in value) or "-"
	return str(value)
