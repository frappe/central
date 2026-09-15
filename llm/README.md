# Agent Tooling Setup

Install the tools that you need. Start a new agent session after you install a skill.

## Frappe skills

Install the [Frappe skill collection](https://github.com/frappe/skills):

```bash
npx skills@latest add frappe/skills -g -a claude-code -s '*' -y
```

This gives `code-style`, `quality-code-review`, `technical-writing`, `ui-design`, `draft-security-advisory`, and `resolve-backport-conflicts`.

Do not use `frappe-app-dev` in this repository. Its scaffolding conflicts with the Central object model.

## Review skills

Install [`grill-me`](https://github.com/mattpocock/skills) for strict review of a plan or a change before handover:

```bash
npx skills@latest add mattpocock/skills -g -a claude-code -s grill-me -y
```

Use `review-like-ankush` for a Frappe diff or pull request review when the skill is available.

## Focused output

Install [`i-have-adhd`](https://github.com/ayghri/i-have-adhd) for focused, action-first output:

```bash
npx skills@latest add ayghri/i-have-adhd -g -a claude-code -s '*' -y
```

Invoke it with your agent's skill command.

## Review rules

[`.greptile/rules.md`](../.greptile/rules.md) holds the automated review rules for this repository. Keep it in step with [`CLAUDE.md`](../CLAUDE.md).
