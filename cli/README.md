# Central CLI

`central` manages Frappe Cloud servers, private networks and services from the terminal. It calls the same Central API as the console, so a command can do only what your team role lets you do in the console.

## Install

The CLI needs Python 3.11 or later.

```bash
uv tool install "git+https://github.com/frappe/central.git#subdirectory=cli"
```

## Sign in

Sign in with a code that Central sends to your email. The CLI saves the session in `~/.config/central/config.json`, readable by you only.

```bash
central auth login --url https://central.example.com
central team list
central team use my-team
```

A script or an agent can use an API key instead of a session. Set `CENTRAL_URL`, `CENTRAL_API_KEY` and `CENTRAL_API_SECRET`. An API key wins over a saved session.

## Settings

Each command takes `--url`, `--team` and `--json`. A flag wins over the environment, and the environment wins over the saved config.

| Setting | Flag | Environment |
|---|---|---|
| Central URL | `--url` | `CENTRAL_URL` |
| Team | `--team` | `CENTRAL_TEAM` |
| Config file | | `CENTRAL_CONFIG` |

The URL must use `https://`. Plain `http://` is accepted only for a local development site, such as `http://central.localhost:8000`. The CLI does not follow a redirect, so it never sends your credentials to another host.

When you are in one team only, commands use that team. Use `--json` for output that a script or an agent can read.

## Commands

| Command | Use it to |
|---|---|
| `central auth login`, `logout`, `whoami` | Sign in and out. |
| `central team list`, `use`, `members`, `invite` | Choose a team and manage its members. |
| `central region list` | See where servers can run. |
| `central offering list`, `central image list` | See the images a server can start from. |
| `central plan list` | See server plans and prices. |
| `central server list`, `show`, `create`, `rename` | Manage servers. |
| `central server start`, `stop`, `restart`, `terminate`, `wait` | Run server actions. |
| `central server console`, `ssh` | Open a shell on a server. |
| `central snapshot list`, `create`, `delete` | Manage server snapshots. |
| `central ssh-key list`, `add`, `delete` | Manage the team's SSH keys. |
| `central wireguard list`, `create`, `delete`, `allow`, `deny` | Reach servers on their private network. |
| `central bucket list`, `regions`, `create`, `usage`, `rotate`, `delete` | Manage object storage buckets. |
| `central ai status`, `enable`, `models`, `keys`, `create-key`, `revoke-key`, `usage` | Use hosted LLM models. |

Run `central <command> --help` for the options of a command. A server argument takes the server ID or its title.

## Examples

Create a server from the newest image of an offering, and wait until it runs:

```bash
central server create web-1 --region blr1 --plan small --offering ubuntu --ssh-key my-laptop --wait
```

Open a shell on the server. `console` opens the web console in your browser. `ssh` uses your SSH client and your team SSH key:

```bash
central server console web-1
central server ssh web-1 -- -L 8000:localhost:8000
```

Connect this machine to the servers of a region over WireGuard. The CLI makes the key pair on your machine and sends only the public key to Central:

```bash
central wireguard create --region blr1 --title my-laptop
central wireguard allow web-1
sudo wg-quick up ./my-laptop.conf
central server ssh web-1
```

Destructive commands ask for confirmation. Pass `--yes` to skip the question in a script.

## Development

```bash
cd cli
uv sync
uv run pytest
uv run central --help
```
