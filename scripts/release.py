#!/usr/bin/env python3
"""Bump Central's version in the two files that carry it.

Edits central/__init__.py (read by Frappe and flit) and package.json (the
dashboard) so they stay in sync, then prints the diff. It does not commit or
tag — review the change, make a `chore(release): vX.Y.Z` commit, and publish
the release from GitHub. See RELEASING.md.

Run from the app root:
    python scripts/release.py 0.1.0
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT_PY = ROOT / "central" / "__init__.py"
PACKAGE_JSON = ROOT / "package.json"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def current_version() -> str:
	match = re.search(r'__version__ = "([^"]*)"', INIT_PY.read_text())
	return match.group(1) if match else "?"


def set_init_version(version: str) -> None:
	text = INIT_PY.read_text()
	new = re.sub(r'__version__ = "[^"]*"', f'__version__ = "{version}"', text, count=1)
	if new == text:
		sys.exit(f"ERROR: could not find __version__ in {INIT_PY}")
	INIT_PY.write_text(new)


def set_package_version(version: str) -> None:
	data = json.loads(PACKAGE_JSON.read_text())
	data["version"] = version
	PACKAGE_JSON.write_text(json.dumps(data, indent=2) + "\n")


def main() -> int:
	if len(sys.argv) != 2:
		sys.exit("usage: python scripts/release.py <major.minor.patch>")

	version = sys.argv[1].lstrip("v")
	if not SEMVER.match(version):
		sys.exit(f"ERROR: '{version}' is not valid SemVer (expected e.g. 0.1.0)")

	print(f"{current_version()} -> {version}")
	set_init_version(version)
	set_package_version(version)

	subprocess.run(["git", "--no-pager", "diff", "--", str(INIT_PY), str(PACKAGE_JSON)], cwd=ROOT)
	print("\nNext:")
	print(f'  git commit -am "chore(release): v{version}"')
	print(f"  git push, then draft the v{version} release on GitHub with generated notes.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
