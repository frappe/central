"""Typed task I/O — copied from Atlas's scripts/lib/atlas/_task.py (Atlas spec
principle 6: don't import across repos — copy the slice and keep it in sync).

- `TaskInputs`: a frozen dataclass per task. Each field becomes a `--kebab-case` CLI
  flag, typed from the annotation, required unless it declares a default.
  `from_args()` parses argv once into the typed object and gives `--help` for free.
- `TaskResult`: a frozen dataclass per task. `emit()` prints exactly one
  `ATLAS_RESULT=<json>` line; the controller half (`central.host_task.parse_result`)
  recovers it. The marker token stays `ATLAS_RESULT=` so the runner and parser are
  byte-identical to Atlas's — one shared wire contract, not a Central-only fork.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import typing
from dataclasses import dataclass

RESULT_MARKER = "ATLAS_RESULT="

T = typing.TypeVar("T", bound="TaskInputs")
R = typing.TypeVar("R", bound="TaskResult")


@dataclass(frozen=True)
class TaskInputs:
	"""Base for a task's typed inputs. Subclass with annotated fields; each field
	maps to a `--kebab-case` flag. Fields with a default are optional; everything
	else is a required argument."""

	command: typing.ClassVar[str] = ""

	@classmethod
	def build_parser(cls, parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
		parser = parser or argparse.ArgumentParser(prog=cls.command or None, description=cls.__doc__)
		for field in dataclasses.fields(cls):
			flag = "--" + field.name.replace("_", "-")
			required = not _has_default(field)
			if _is_list(field):
				parser.add_argument(
					flag,
					dest=field.name,
					action="append",
					default=None,
					required=required,
					help=_field_help(field),
				)
			else:
				parser.add_argument(
					flag,
					dest=field.name,
					type=_arg_type(field),
					required=required,
					default=None if required else _default(field),
					help=_field_help(field),
				)
		return parser

	@classmethod
	def from_args(cls: type[T], argv: typing.Sequence[str] | None = None) -> T:
		namespace = cls.build_parser().parse_args(argv)
		values = {}
		for field in dataclasses.fields(cls):
			value = getattr(namespace, field.name)
			if _is_list(field) and value is None:
				value = _default(field) if _has_default(field) else []
			values[field.name] = value
		return cls(**values)


@dataclass(frozen=True)
class TaskResult:
	"""Base for a task's typed result. Subclass with annotated fields. `emit()` writes
	the one machine-readable line; `parse()` recovers it controller-side."""

	def emit(self) -> None:
		print(RESULT_MARKER + json.dumps(dataclasses.asdict(self)))

	@classmethod
	def parse(cls: type[R], stdout: str) -> R:
		for line in reversed((stdout or "").splitlines()):
			if line.startswith(RESULT_MARKER):
				payload = json.loads(line[len(RESULT_MARKER) :])
				return cls(**payload)
		raise ValueError(f"no {RESULT_MARKER} line in task output")


def _has_default(field: dataclasses.Field) -> bool:
	return (
		field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING  # type: ignore[misc]
	)


def _default(field: dataclasses.Field) -> typing.Any:
	if field.default is not dataclasses.MISSING:
		return field.default
	return field.default_factory()  # type: ignore[misc]


def _is_list(field: dataclasses.Field) -> bool:
	annotation = field.type
	if isinstance(annotation, str):
		return annotation.startswith("list")
	return annotation is list or typing.get_origin(annotation) is list


def _arg_type(field: dataclasses.Field) -> typing.Callable[[str], typing.Any]:
	if field.type in (int, "int"):
		return int
	return str


def _field_help(field: dataclasses.Field) -> str:
	return field.metadata.get("help", "")
