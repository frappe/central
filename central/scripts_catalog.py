"""Catalog of host scripts Central's local runner may execute.

The sibling of Atlas's `atlas.atlas.scripts_catalog`, trimmed to what Central needs:
the WireGuard hub scripts under `central/scripts/`. `resolve()` is the gate the
host-task runner (`central.host_task`) goes through — it refuses anything not in
`HUB_SCRIPTS`, so the privileged runner can only ever invoke the three pinned
scripts, never an arbitrary path.
"""

from __future__ import annotations

import functools
from pathlib import Path

import frappe

# The only scripts the local runner will execute. Each is sudoers-pinned on the host
# (scripts/sudoers.d/central-tunnel). Keep in lockstep with that drop-in.
HUB_SCRIPTS: frozenset[str] = frozenset(
	{
		"hub-up.py",
		"hub-peer-add.py",
		"hub-peer-remove.py",
	}
)


@functools.lru_cache(maxsize=1)
def _repo_root() -> Path:
	# Cached per-process. Tests that monkeypatch frappe.get_app_path must call
	# _repo_root.cache_clear().
	return Path(frappe.get_app_path("central", "..")).resolve()


def scripts_directory() -> Path:
	return _repo_root() / "scripts"


def resolve(script: str) -> Path:
	"""Locate a hub script under `central/scripts/`. Raises ValueError for anything
	not in `HUB_SCRIPTS` (the privileged-runner gate) and FileNotFoundError if the
	allowed script is somehow missing on disk."""
	if script not in HUB_SCRIPTS:
		raise ValueError(f"{script!r} is not an allowed hub script: {sorted(HUB_SCRIPTS)}")
	candidate = scripts_directory() / script
	if not candidate.is_file():
		raise FileNotFoundError(f"Hub script not found: {candidate}")
	return candidate
