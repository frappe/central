#!/usr/bin/env bash
# Usage: measure.sh <site> <app> <app-source-dir> <out-dir> [exclude-regex]
# Run inside a bench with services up and the site migrated. Runs each test module in its own
# coverage process (one long process loses per-test contexts for many classes), appending to
# <out-dir>/.coverage. Writes <out-dir>/frappe.testing.log, <out-dir>/modules.tsv (module, seconds, result).
set -uo pipefail

site=$1 app=$2 source=$(cd "$3" && pwd) out=$(mkdir -p "$4" && cd "$4" && pwd) exclude=${5:-^$}

bench=$PWD
while [ ! -d "$bench/sites" ] && [ "$bench" != / ]; do bench=$(dirname "$bench"); done
[ -d "$bench/sites" ] || { echo "not inside a bench" >&2; exit 1; }

cat > "$out/coveragerc" <<EOF
[run]
source = $source/$app
data_file = $out/.coverage
dynamic_context = test_function
branch = True
omit = */tests/*, */test_*.py, */patches/*
EOF

cat > "$out/driver.py" <<EOF
import runpy, sys
sys.argv = ["frappe", "frappe", "--site", "$site", "run-tests", "--app", "$app", "--module", sys.argv[1]]
runpy.run_module("frappe.utils.bench_helper", run_name="__main__")
EOF

rm -f "$out/.coverage" "$out/modules.tsv" "$out/frappe.testing.log"
cd "$source"
modules=$(find "$app" -name 'test_*.py' -not -path '*/node_modules/*' | sed 's#\.py$##; s#/#.#g' | sort | grep -Ev "$exclude")
cd "$bench/sites"

for module in $modules; do
	: > "$bench/logs/frappe.testing.log"
	started=$(date +%s)
	"$bench/env/bin/python" -m coverage run --append --rcfile="$out/coveragerc" "$out/driver.py" "$module" > "$out/last.log" 2>&1
	result=$(grep -E "^(OK|FAILED)" "$out/last.log" | tail -1)
	printf '%s\t%s\t%s\n' "$module" "$(( $(date +%s) - started ))" "${result:-no result}" | tee -a "$out/modules.tsv"
	cat "$bench/logs/frappe.testing.log" >> "$out/frappe.testing.log"
	[[ $result == OK* ]] || cp "$out/last.log" "$out/failed-$module.log"
done

echo "saved $out/.coverage, modules.tsv and frappe.testing.log"
