# Central host scripts

Sudoers-pinned scripts that run on the **Central host** (the WireGuard hub), invoked
through the controller-local runner `central.host_task.run_host_task` — the sibling of
Atlas's host/local task runners. See [../spec/TUNNEL.md](../spec/TUNNEL.md) and
[atlas/spec/19-tunnel.md](../../atlas/spec/19-tunnel.md).

## The contract (reused from Atlas, verbatim)

Each script is a typed CLI: `--kebab-case` flags in (`lib/central/_task.py`
`TaskInputs`), one `ATLAS_RESULT=<json>` line out (`TaskResult.emit`), which the
controller recovers with `central.host_task.parse_result`. Pure string/argv builders
(`lib/central/wireguard.py`) are unit-testable with bare `python3 -m unittest`; only
the apply functions touch the host (`lib/central/_run.py` is the one subprocess
module). This is a faithful copy of Atlas's `scripts/lib/atlas/` contract (Atlas spec
principle 6: don't import across repos — copy and keep in sync).

## Scripts

| Script | Purpose |
| --- | --- |
| `hub-up.py` | Bring up `wg0` idempotently (generate the hub keypair if absent, write `wg0.conf`, `wg-quick up`, enable `wg-quick@wg0`); emit the hub public key. |
| `hub-peer-add.py` | Add/update one Atlas peer (`wg set … endpoint … persistent-keepalive 25`) and persist (`wg-quick save`). |
| `hub-peer-remove.py` | Remove one Atlas peer and persist (rollback / de-register). |

## One-time operator install

1. Install `wireguard-tools` on the Central host (provides `wg`, `wg-quick`,
   `/etc/wireguard`).
2. Stage these scripts where the bench runs them (they run in place from the app
   repo; no separate staging needed for the single-host hub).
3. Install the sudoers drop-in (pins the exact privileged commands):
   ```
   sudo install -m 0440 -o root -g root \
       scripts/sudoers.d/central-tunnel /etc/sudoers.d/central-tunnel
   sudo visudo -cf /etc/sudoers.d/central-tunnel
   ```
   Edit it first to match your bench OS user and binary paths (see the file header).
4. In Desk: **Central Tunnel Settings** → set the key path / endpoint / pool, then
   **Initialize Hub**.
