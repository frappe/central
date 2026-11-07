# Frappe Cloud CLI

`fcloud` manages Frappe Cloud servers, private networks and services from the terminal. It calls the same Central API as the console, so a command can do only what your team role lets you do in the console.

## Install

The CLI needs Python 3.11 or later. The package is `frappe-cloud`. It installs the `fcloud` command and `fcctl`, an alias of the same command.

```bash
uv tool install "git+https://github.com/frappe/central.git#subdirectory=cli"
```

## Sign in

Sign in with a code that Central sends to your email. The CLI saves only the site URL, the session and your default team in `~/.config/frappe-cloud/config.json`, readable by you only. It reads everything else from Central.

```bash
fcloud auth login --url https://central.example.com
fcloud team list
fcloud team use my-team
```

A script or an agent can use an API key instead of a session. Set `FRAPPE_CLOUD_URL`, `FRAPPE_CLOUD_API_KEY` and `FRAPPE_CLOUD_API_SECRET`. An API key wins over a saved session. With an API key, set the team with `FRAPPE_CLOUD_TEAM` or `--team`, because `fcloud team use` saves a team only for the site you signed in to.

## Settings

Each command takes `--url`, `--team` and `--json`. A flag wins over the environment, and the environment wins over the saved config.

| Setting | Flag | Environment |
|---|---|---|
| Central URL | `--url` | `FRAPPE_CLOUD_URL` |
| Team | `--team` | `FRAPPE_CLOUD_TEAM` |
| Config file | | `FRAPPE_CLOUD_CONFIG` |

The URL must use `https://`. Plain `http://` is accepted only for a local development site, such as `http://central.localhost:8000`. The CLI does not follow a redirect, so it never sends your credentials to another host.

The saved session and team apply only to the URL you signed in to. When `--url` or `FRAPPE_CLOUD_URL` names another site, the CLI does not send the saved session to it.

When you are in one team only, commands use that team. Use `--json` for output that a script or an agent can read.

## Commands

| Command | Use it to |
|---|---|
| `fcloud auth login`, `logout`, `whoami` | Sign in and out. |
| `fcloud team list`, `use`, `members`, `invite` | Choose a team and manage its members. |
| `fcloud region list` | See where servers can run. |
| `fcloud offering list`, `fcloud image list` | See the images a server can start from. |
| `fcloud plan list` | See server plans and prices. |
| `fcloud server list`, `show`, `create`, `rename` | Manage servers. |
| `fcloud server start`, `stop`, `restart`, `terminate`, `wait` | Run server actions. |
| `fcloud server console`, `ssh` | Open a shell on a server. |
| `fcloud snapshot list`, `create`, `delete` | Manage server snapshots. |
| `fcloud ssh-key list`, `add`, `delete` | Manage the team's SSH keys. |
| `fcloud wireguard list`, `create`, `delete`, `allow`, `deny` | Reach servers on their private network. |
| `fcloud bucket list`, `regions`, `create`, `usage`, `rotate`, `delete` | Manage object storage buckets. |
| `fcloud ai status`, `enable`, `models`, `keys`, `create-key`, `revoke-key`, `usage` | Use hosted LLM models. |

Run `fcloud <command> --help` for the options of a command. A server argument takes the server ID or its title.

## Examples

Create a server from the newest image of an offering, and wait until it runs:

```bash
fcloud server create web-1 --region blr1 --plan small --offering ubuntu --ssh-key my-laptop --wait
```

Open a shell on the server. `console` opens the web console in your browser. `ssh` uses your SSH client and your team SSH key:

```bash
fcloud server console web-1
fcloud server ssh web-1 -- -L 8000:localhost:8000
```

Connect this machine to the servers of a region over WireGuard. The CLI makes the key pair on your machine and sends only the public key to Central:

```bash
fcloud wireguard create --region blr1 --title my-laptop
fcloud wireguard allow web-1
sudo wg-quick up ./my-laptop.conf
fcloud server ssh web-1
```

Destructive commands ask for confirmation. Pass `--yes` to skip the question in a script.

## Development

```bash
cd cli
uv sync
uv run pytest
uv run fcloud --help
```
