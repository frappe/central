# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Database-level money invariants — rung 1 of the enforcement ladder (ADR 0018).

Frappe's DocType JSON cannot express a `CHECK` constraint, so the invariants that
belong in the database are declared here and applied as DDL. This module is the
registry: every rung-1 invariant in billing is one row in `CONSTRAINTS`.

**This is a hook, not a patch, and that distinction is load-bearing.** A patch runs
once and is then recorded as done — and on a *fresh* site Frappe marks every patch
in `patches.txt` as already-executed without running it. A constraint declared only
in a patch would therefore exist on migrated sites and be silently absent on new
ones, which is the "a fresh site is quietly weaker than a migrated one" failure the
ADR forbids. Running from `after_install` / `after_migrate` / `before_tests` makes
the constraint a property of the schema rather than of a site's migration history.

Idempotent: each constraint is added only if it is not already present, so this is
safe to run on every migrate.
"""

import frappe

# (table, constraint name, check clause) — the invariant, at the only rung that
# holds against every caller including `frappe.db.set_value`, which skips the
# controller entirely.
CONSTRAINTS = (
	(
		"tabCredit Wallet",
		"credit_wallet_balance_non_negative",
		"`balance` >= 0",
	),
)


def existing_constraints(table: str) -> set[str]:
	rows = frappe.db.sql(
		"""
		select constraint_name from information_schema.check_constraints
		where constraint_schema = database() and table_name = %s
		""",
		(table,),
	)
	return {r[0] for r in rows}


def ensure_constraints() -> list[str]:
	"""Apply every missing rung-1 constraint. Returns the names newly added."""
	added = []
	for table, name, clause in CONSTRAINTS:
		if not frappe.db.table_exists(table.removeprefix("tab")):
			continue
		if name in existing_constraints(table):
			continue
		frappe.db.sql_ddl(f"alter table `{table}` add constraint `{name}` check ({clause})")
		added.append(name)
		frappe.logger("billing").info(f"added CHECK constraint {name} on {table}")
	return added
