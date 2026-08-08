"""Controller-local host-task runner for Central — the hub's privileged script runner.

The minimal sibling of Atlas's `atlas.atlas.local_task.run_local_task`. Central has
no host-exec today; the WireGuard hub (central/spec/TUNNEL.md) needs to run a handful
of sudoers-pinned scripts (`central/scripts/*.py`) on its *own* host. This executes
one such script as a local subprocess, records a `Host Task` audit row (the operator
sees every privileged action in one list), and the caller recovers the typed
`ATLAS_RESULT=` payload with `parse_result`.

It reuses Atlas's wire contract verbatim — `--kebab-case` flags in, one
`ATLAS_RESULT=` JSON line out (atlas spec/04-tasks.md) — rather than inventing a new
one. The two small helpers Atlas keeps in `_ssh.runner` and `task_results` are copied
here (`_variables_to_flags`, `parse_result`) because the apps live in separate repos
(atlas spec principle 6: don't import — copy). Secrets go through `env`, never argv,
so they never appear in `ps`.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import frappe
from frappe import _

from central.scripts_catalog import resolve

if TYPE_CHECKING:
	from central.central.doctype.host_task.host_task import HostTask

RESULT_MARKER = "ATLAS_RESULT="


def run_host_task(
	*,
	script: str,
	variables: dict,
	env: dict[str, str] | None = None,
	timeout_seconds: int = 300,
) -> "HostTask":
	"""Run `script` locally as `python3 <script> --flags …`, recording a Host Task row.

	`variables` maps UPPER_SNAKE → value, rendered to `--kebab-case` flags exactly as
	Atlas's SSH/local runners do. `env` carries any secrets into the subprocess
	environment — kept out of argv on purpose. Raises frappe.ValidationError on any
	failure; the Host Task row is always saved first."""
	task = frappe.get_doc(
		{
			"doctype": "Host Task",
			"script": script,
			"status": "Pending",
			"triggered_by": frappe.session.user if frappe.session else "Administrator",
		}
	)
	task.variables = frappe.as_json(variables)
	task.insert(ignore_permissions=True)

	_execute(task, script, variables, env or {}, timeout_seconds)
	return task


def parse_result(stdout: str) -> dict:
	"""Return the decoded `ATLAS_RESULT=` payload from a task's stdout (the LAST
	marker line wins). Raises ValueError if no marker is present — a task that
	declares a typed result must produce one, so a truncated run surfaces loudly.
	Copied from atlas.atlas.task_results.parse_result; the marker is the shared
	contract."""
	for line in reversed((stdout or "").splitlines()):
		if line.startswith(RESULT_MARKER):
			return json.loads(line[len(RESULT_MARKER) :])
	raise ValueError(f"no {RESULT_MARKER} line in task output")


def _execute(
	task: "HostTask",
	script: str,
	variables: dict,
	env: dict[str, str],
	timeout_seconds: int,
) -> None:
	task.status = "Running"
	task.started = frappe.utils.now_datetime()
	task.save(ignore_permissions=True)
	# nosemgrep: frappe-manual-commit -- persist the Running state before the long-running local subprocess so a crash mid-run is observable and the Task isn't stuck Pending
	frappe.db.commit()

	start = time.monotonic()
	try:
		stdout, stderr, exit_code = _run_script(script, variables, env, timeout_seconds)
	except subprocess.TimeoutExpired as timeout:
		_finalize(task, "", f"Timed out after {timeout.timeout}s", None, "Failure", _elapsed_ms(start))
		frappe.throw(_("Host Task {0} timed out after {1}s").format(task.name, timeout.timeout))
	except Exception as exception:
		_finalize(task, "", str(exception), None, "Failure", _elapsed_ms(start))
		raise frappe.ValidationError(str(exception)) from exception

	status = "Success" if exit_code == 0 else "Failure"
	_finalize(task, stdout, stderr, exit_code, status, _elapsed_ms(start))
	if status == "Failure":
		frappe.throw(_("Host Task {0} ({1}) exited {2}: {3}").format(task.name, script, exit_code, stderr[-500:]))


def _run_script(
	script: str,
	variables: dict,
	env: dict[str, str],
	timeout_seconds: int,
) -> tuple[str, str, int]:
	script_path = resolve(script)
	flags = _variables_to_flags(variables)
	argv = [sys.executable, str(script_path), *shlex.split(flags)]
	subprocess_env = {**os.environ, **env}
	result = subprocess.run(
		argv,
		capture_output=True,
		text=True,
		timeout=timeout_seconds,
		check=False,
		env=subprocess_env,
	)
	return result.stdout, result.stderr, result.returncode


def _variables_to_flags(variables: dict) -> str:
	"""Render a variables dict as a CLI argument string: UPPER_SNAKE → --kebab, list →
	repeated flag, everything quoted. Empty/None values are dropped (the field's
	default applies). Copied from atlas.atlas._ssh.runner._variables_to_flags."""
	parts: list[str] = []
	for key, value in variables.items():
		flag = "--" + key.lower().replace("_", "-")
		if isinstance(value, (list, tuple)):
			for item in value:
				parts += [flag, shlex.quote(str(item))]
		elif value is None or value == "":
			continue
		else:
			parts += [flag, shlex.quote(str(value))]
	return " ".join(parts)


def _finalize(
	task: "HostTask",
	stdout: str,
	stderr: str,
	exit_code: int | None,
	status: str,
	elapsed_ms: int,
) -> None:
	task.stdout = stdout
	task.stderr = stderr
	task.exit_code = exit_code
	task.status = status
	task.ended = frappe.utils.now_datetime()
	task.duration_milliseconds = elapsed_ms
	task.save(ignore_permissions=True)
	# nosemgrep: frappe-manual-commit -- persist the Task outcome before run_host_task re-raises so the final status survives the raise
	frappe.db.commit()


def _elapsed_ms(start: float) -> int:
	return int((time.monotonic() - start) * 1000)


HOST_TASK_RETENTION_DEFAULT_DAYS = 30


def prune_host_tasks(now=None) -> dict:
	"""Daily: drop finished Host Tasks past the retention window.

	A Host Task is the record of one run of a privileged host/hub script (the
	WireGuard hub + tunnel scripts driven by `run_host_task`): it captures the
	script name, exit code, status, and the full stdout/stderr as longtext. It is
	an operational audit log, not a system of record — nothing downstream reads an
	old task — so the rows accumulate one-per-run and the longtext columns grow the
	table without bound. Prune terminal tasks (Success/Failure) older than
	`host_task_retention_days` (default 30 days); live tasks (Pending/Running) are
	kept regardless of age. Modelled on billing's cleanup_payment_logs."""
	days = int(frappe.conf.get("host_task_retention_days") or HOST_TASK_RETENTION_DEFAULT_DAYS)
	cutoff = frappe.utils.add_to_date(now or frappe.utils.now_datetime(), days=-days)
	names = frappe.get_all(
		"Host Task",
		filters={"status": ("in", ("Success", "Failure")), "creation": ("<", cutoff)},
		pluck="name",
	)
	for name in names:
		frappe.delete_doc("Host Task", name, ignore_permissions=True, force=True)
	return {"cutoff": str(cutoff), "deleted": len(names)}
