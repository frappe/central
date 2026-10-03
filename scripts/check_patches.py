#!/usr/bin/env python3
"""CI guard: every patch module under central/patches/v0_0/ must be listed in
central/patches.txt, so a patch is never written and silently never run.

Run: python scripts/check_patches.py  (from the app root)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHES_DIR = ROOT / "central" / "patches" / "v0_0"
PATCHES_TXT = ROOT / "central" / "patches.txt"


def main() -> int:
	on_disk = {p.stem for p in PATCHES_DIR.glob("*.py") if p.stem != "__init__"}
	listed_text = PATCHES_TXT.read_text()
	unlisted = {m for m in on_disk if f"central.patches.v0_0.{m}" not in listed_text}

	if unlisted:
		print("ERROR: patch modules exist on disk but are not in patches.txt:")
		for name in sorted(unlisted):
			print(f"  - central.patches.v0_0.{name}")
		print("Add them to central/patches.txt (or delete them).")
		return 1

	print(f"OK: {len(on_disk)} patches listed.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
