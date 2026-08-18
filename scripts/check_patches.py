#!/usr/bin/env python3
"""CI guard: every patch module under central/patches/v0_0/ must be listed in
central/patches.txt, so a patch is never written and silently never run.

Five billing-owned modules pre-date this guard and are knowingly unlisted
(tracked in the refactor plan, out of scope to wire up). They are allow-listed
below; anything *new* that is unlisted fails CI. Removing an allow-listed entry
once it is wired into patches.txt is the intended end state — do not add to this
list to silence a new orphan.

Run: python scripts/check_patches.py  (from the app root)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Known pre-existing orphans (billing-owned, out of scope). Do not extend.
KNOWN_ORPHANS = {
	"backfill_period_key",
	"billing_hot_indexes",
	"drop_dup_credit_ledger_index",
	"namespace_gateway_payment_ids",
	"rekey_wallet_per_currency",
}

ROOT = Path(__file__).resolve().parent.parent
PATCHES_DIR = ROOT / "central" / "patches" / "v0_0"
PATCHES_TXT = ROOT / "central" / "patches.txt"


def main() -> int:
	on_disk = {p.stem for p in PATCHES_DIR.glob("*.py") if p.stem != "__init__"}
	listed_text = PATCHES_TXT.read_text()
	listed = {m for m in on_disk if f"central.patches.v0_0.{m}" in listed_text}

	unlisted = on_disk - listed
	new_orphans = unlisted - KNOWN_ORPHANS
	if new_orphans:
		print("ERROR: patch modules exist on disk but are not in patches.txt:")
		for name in sorted(new_orphans):
			print(f"  - central.patches.v0_0.{name}")
		print("Add them to central/patches.txt (or delete them).")
		return 1

	stale_allow = KNOWN_ORPHANS - unlisted
	if stale_allow:
		print(
			"ERROR: KNOWN_ORPHANS in scripts/check_patches.py are stale (now "
			"listed or deleted). Remove them from the allow-list:"
		)
		for name in sorted(stale_allow):
			print(f"  - {name}")
		return 1

	print(f"OK: {len(listed)} patches listed, {len(KNOWN_ORPHANS)} known orphans.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
