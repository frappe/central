"""The one place that touches the host — copied from Atlas's scripts/lib/atlas/_run.py.

Central's hub scripts run privileged host commands (`wg`, `wg-quick`, `nft`,
`systemctl`) the same way Atlas's host scripts do: a real argv (no shell), echo-
every-command tracing into the Task log, abort-on-first-failure. Atlas's package is
staged on a different host and can't be imported across repos, so we copy the small
slice we need (Atlas spec principle 6: don't import — copy; keep them in sync). This
is the *only* module here that runs a subprocess; everything else is pure functions
over strings, so everything else is unit-testable without a host.
"""

import os
import shlex
import subprocess
import sys
import tempfile
import time


def _trace(argv: list[str]) -> float:
	"""Echo the `set -x` trace line for `argv` to stderr and return a monotonic
	start time. Pair with `_traced` to print the command's wall-clock duration."""
	print("+ " + shlex.join(argv), file=sys.stderr, flush=True)
	return time.monotonic()


def _traced(argv: list[str], start: float) -> None:
	"""Close the trace opened by `_trace`: print `+ (<elapsed>) <command>` so each
	command's duration sits next to its invocation in the Task log (stderr)."""
	elapsed = time.monotonic() - start
	print(f"+ ({elapsed:.3f}s) {shlex.join(argv)}", file=sys.stderr, flush=True)


class CommandError(RuntimeError):
	"""A command exited non-zero. Carries the argv, code, and captured output so
	the Task log (stderr) shows exactly what failed."""

	def __init__(self, argv: list[str], returncode: int, output: str):
		self.argv = argv
		self.returncode = returncode
		self.output = output
		super().__init__(f"command failed (exit {returncode}): {shlex.join(argv)}\n{output}")


def run(*argv: str, check: bool = True, quiet: bool = False) -> str:
	"""Run one command, echo it (the `set -x` trace), return its stdout.

	`argv` is a real argument vector — no shell, so no quoting hazards. On non-zero
	exit raises CommandError unless `check=False` (the Python form of `|| true`). The
	`+ <command>` line goes to stderr so it never pollutes stdout a caller parses."""
	start = _trace(list(argv))
	result = subprocess.run(argv, capture_output=True, text=True, check=False)
	_traced(list(argv), start)
	if result.stderr and not quiet:
		sys.stderr.write(result.stderr)
		sys.stderr.flush()
	if check and result.returncode != 0:
		raise CommandError(list(argv), result.returncode, result.stdout + result.stderr)
	return result.stdout


def run_ok(*argv: str) -> bool:
	"""Run a command purely as a boolean gate — the Python form of `cmd >/dev/null
	2>&1` used in an `if`. Never raises, never prints output; True iff exit 0."""
	result = subprocess.run(argv, capture_output=True, text=True, check=False)
	return result.returncode == 0


def run_input(*argv: str, stdin: str) -> str:
	"""Run a command feeding `stdin` to its standard input — the Python form of
	`printf ... | cmd` (e.g. `wg pubkey` reading a private key). Echoes the command,
	raises CommandError on non-zero, returns stdout."""
	start = _trace(list(argv))
	result = subprocess.run(argv, input=stdin, capture_output=True, text=True, check=False)
	_traced(list(argv), start)
	if result.stderr:
		sys.stderr.write(result.stderr)
		sys.stderr.flush()
	if result.returncode != 0:
		raise CommandError(list(argv), result.returncode, result.stdout + result.stderr)
	return result.stdout


def install_file(content: str, dest: str, *, mode: str = "0644", sudo: bool = True) -> None:
	"""Write `content` to `dest` with `mode`, atomically, via `install -m <mode> <src>
	<dest>`. `src` is a real (seekable) temp file, not `/dev/stdin` — uutils `install`
	(the Ubuntu default) cannot reliably copy from a non-seekable pipe."""
	with tempfile.NamedTemporaryFile("w", prefix="central-install-", delete=False) as spool:
		spool.write(content)
		# nosemgrep: tempfile-without-flush -- false positive: the file is closed (and flushed) by the with-block exit before install reads src below
		src = spool.name
	try:
		argv = (["sudo"] if sudo else []) + ["install", "-m", mode, src, dest]
		run(*argv)
	finally:
		os.unlink(src)


def install_directory(dest: str, *, mode: str = "0700", sudo: bool = True) -> None:
	"""`install -d -m <mode> <dest>` — create a directory with an explicit mode."""
	argv = (["sudo"] if sudo else []) + ["install", "-d", "-m", mode, dest]
	run(*argv)
