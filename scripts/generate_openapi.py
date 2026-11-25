import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from central.api.openapi import build_document

OUTPUT = Path(__file__).resolve().parents[1] / "central" / "public" / "openapi.json"


def main() -> None:
	spec = build_document()
	OUTPUT.write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n")
	print(OUTPUT)
	print(f"{sum(len(methods) for methods in spec['paths'].values())} operations")


if __name__ == "__main__":
	main()
