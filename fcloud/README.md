# fcloud

`fcloud` is the command line client for Frappe Cloud. It talks to Central. Today it connects a repository to push-to-deploy, lists deploys, and follows deploy logs.

## Install

Install it with uv or pip. It needs Python 3.11 or later.

```bash
uv tool install "git+https://github.com/frappe/central#subdirectory=fcloud"
pip install "git+https://github.com/frappe/central#subdirectory=fcloud"
```

From a checkout of this repository, use `uv tool install ./fcloud`.

## Log in

`fcloud auth login` opens the browser and signs you in to Central with OAuth. The CLI registers itself as a public OAuth client on the first login, so there is no client secret to keep.

```bash
fcloud auth login dashboard.frappe.io
```

The login listens on `127.0.0.1:9876` for the redirect. When the browser runs on another machine, for example over SSH, paste the address the browser ends up on into the terminal.

Use an API key when the site does not offer OAuth:

```bash
fcloud auth login dashboard.frappe.io --api-key
```

| Command | Result |
|---|---|
| `fcloud auth list` | Lists the profiles. `*` marks the default. |
| `fcloud auth default <name>` | Sets the default profile. |
| `fcloud auth whoami` | Shows the user of the active profile. |
| `fcloud auth logout <name>` | Revokes the session on Central and removes the credentials. |

Use `--profile <name>` before a command to use a profile other than the default, for example `fcloud --profile staging deploy-apps list`.

## Deploy

A deploy app is a repository branch that Central deploys on each push. Run the deploy commands in the git repository of the deploy app. They use the `origin` remote and the current branch. Pass `--repository owner/name` and `--branch` to target another one.

```bash
fcloud launch --region <region>
git push
fcloud logs --follow
```

| Command | Result |
|---|---|
| `fcloud launch --region <region>` | Connects the repository and branch through GitHub. Each push then deploys it. |
| `fcloud deploys` | Lists the deploys of the app, newest first. |
| `fcloud logs [DEPLOY] [-f]` | Shows the tasks and logs of a deploy. The default is the newest deploy. |
| `fcloud secrets list\|set\|unset` | Manages the environment variables of the container. A bare `KEY` asks for its value. |
| `fcloud deploy-apps list` | Lists the deploy apps of a team. |
| `fcloud deploy-apps disable` | Stops deploys on push. The server keeps running. |

`fcloud teams list` lists your active teams.

## Configuration

| Location | Content |
|---|---|
| `~/.config/fcloud/config.json` | The profiles: URL, login method, and OAuth client ID. Set `FCLOUD_CONFIG_DIR` to use another directory. |
| System keyring, service `fcloud` | The OAuth tokens or the API key and secret of each profile. |

In CI, set `FCLOUD_URL`, `FCLOUD_API_KEY`, and `FCLOUD_API_SECRET`. These take precedence over the profiles.

## Development

```bash
cd fcloud
uv sync
uv run pytest
```

| Path | Owns |
|---|---|
| `src/fcloud/cli.py` | The root command, the global options, and how errors become exit codes. |
| `src/fcloud/central.py` | `Central`: the authenticated HTTP session to one site. |
| `src/fcloud/profiles.py` | Profiles in the config file and their secrets in the keyring. |
| `src/fcloud/auth/` | OAuth sign-in, refresh and revocation, and the credential types. |
| `src/fcloud/deploy/` | `DeployApp`, the repository connection, and the deploy log printer. |
| `src/fcloud/commands/` | Thin Typer commands. `cli.py` puts the everyday app commands at the top level and each area in a command group. |

Add a new area of Frappe Cloud as a domain package next to `deploy/` and a command group in `commands/`, for example `fcloud servers`.

## Command naming

Read these rules before you add or rename a command. They keep the command tree predictable as the CLI grows to cover all of Frappe Cloud.

### Rule 1: the top level acts on the deploy app in the working directory

A top-level command or group does not name its subject. Its subject is always the deploy app of the git repository in the working directory. Keep the top level for what a developer does every day on that deploy app.

| Command | Subject |
|---|---|
| `fcloud launch` | Connects the deploy app in the working directory. |
| `fcloud deploys` | Lists the deploys of the deploy app in the working directory. |
| `fcloud logs` | Shows the logs of the deploy app in the working directory. |
| `fcloud secrets set KEY` | Sets a secret of the deploy app in the working directory. |

Do not add a top-level command whose subject is not that deploy app. `fcloud logs` always means the logs of the deploy app, never the logs of a server or a site.

### Rule 2: every other resource is a noun group with verbs

Put each other resource in a command group. Name the group with the plural noun, and name each command with a verb.

```text
fcloud servers create
fcloud servers list
fcloud servers logs <server>
fcloud sites create
fcloud deploy-apps list
```

- Use the plural noun for the group: `servers`, `sites`, `deploy-apps`, `teams`. Join two words with a hyphen.
- Use the same noun as the dashboard, so a person finds the same thing in both.
- Use these verbs for the usual operations: `create`, `list`, `show`, `update`, `delete`. Use a domain verb, such as `resize` or `disable`, only when the operation is not one of these.
- Give a command that acts on one resource the resource name as its first argument: `fcloud servers show <server>`.

### Rule 3: a verb means the same thing everywhere

When two groups have the same verb, the verb does the same kind of operation in both. `list` always prints a table, newest first. `logs` always shows logs, and `-f` always follows them. `disable` always stops a resource without deleting it.

### Rule 4: keep names free for what they mean

- Keep `fcloud deploy` free for a command that starts a deploy of the app in the working directory. Do not use it as a group.
- Keep `apps` free for Frappe apps, such as ERPNext. Call a repository branch that deploys on push a deploy app, as Central does with the `Deploy App` DocType, and manage it with `fcloud deploy-apps`. Do not call it an app alone.

### Checklist for a new command

1. Find the subject of the command. If it is the deploy app in the working directory, and developers use it every day, put it at the top level. Otherwise, put it in the group of its noun.
2. Use a verb from rule 2, or an existing domain verb, before you add a new verb.
3. Use the options that other commands already use for the same thing: `--team`, `--region`, `--repository`, `--branch`, `--follow` or `-f`, `--limit`.
4. Put the behavior in the domain package and keep the command thin.
5. Add the command to the tables in this README.
