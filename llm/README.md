# Agent Tooling Setup

Install the tools that you need. Start a new agent session after you install a skill.

## Frappe skills

Install the [Frappe skill collection](https://github.com/frappe/skills):

```bash
npx skills@latest add frappe/skills -g -a claude-code -s '*' -y
```

This gives `code-style`, `quality-code-review`, `technical-writing`, `ui-design`, `draft-security-advisory`, and `resolve-backport-conflicts`.

Do not use `frappe-app-dev` in this repository. Its scaffolding conflicts with the Central object model.

## Interface skills

Use the [Jakub Krehel interface skills](https://github.com/jakubkrehel/skills) for dashboard work. Read the matching `SKILL.md` before you start. Use the smallest set that covers the task. Use `ui-design` for general design work that these skills do not cover.

| Skill | Use for |
|---|---|
| `better-writing` | Empty states, tooltips, labels, helper text, placeholders, customer-facing errors from the frontend or backend, success messages, and confirmations. |
| `better-accessibility` | Keyboard operation, focus, accessible names, forms, screen reader announcements, zoom, and reduced motion. |
| `better-layout` | Grouping, alignment, responsive structure, reading order, and space for long or translated text. |
| `better-typography` | Text hierarchy, wrapping, truncation, punctuation, and font rendering. |
| `better-ui` | Surface and icon polish, visual states, and motion. |
| `better-interface` | A review of a complete screen or flow across the interface skills. |

Install the task-specific skills for Codex and Claude Code:

```bash
npx skills@latest add jakubkrehel/skills -g -a codex -a claude-code -s better-writing better-accessibility better-layout better-typography better-ui -y
```

For a complete screen or flow review, also install `better-interface` and its color review dependency:

```bash
npx skills@latest add jakubkrehel/skills -g -a codex -a claude-code -s better-interface better-colors -y
```

### Copy

Use `better-writing` whenever you add or change interface copy. Read the surrounding strings first. Keep the same term for each resource and action across labels, tooltips, dialogs, and feedback. Check that each label describes the action or value it represents.

This includes backend error messages shown to customers through API responses, validation failures, or the error envelope in `central/errors.py`. Review the customer message and its recovery step. Keep exception types, error codes, diagnostic details, and permission checks intact. Keep customer-facing backend strings wrapped in `_()`. Do not apply this copy review to messages intended only for admins or developers, such as operator-only Desk errors, logs, or tracebacks.

- An initial empty state explains what belongs there and gives one next action that the current user can take.
- A filtered empty state explains that no items match and offers a way to clear the search or filters.
- A tooltip adds useful context. Keep required instructions visible as helper text.
- A button names its action. A placeholder gives an example and does not replace a label.
- An error keeps the actual cause clear and gives a recovery step that the interface supports. Preserve useful details such as a missing setting, an inactive region, or a provider response with no amount. Do not replace a known cause with a generic availability message or promise that a retry can fix a permission or validation failure.
- A destructive confirmation names the resource and states what the action removes or changes.

For example, an empty server list can use the title "No servers yet" and the action "Create server" when the user has permission. A filtered list can use "No servers match these filters" and "Clear filters". Do not show a creation action to a user who cannot create the resource.

### Design and validation

Central uses Vue 3, TypeScript, Frappe UI, and Espresso. Use existing components and semantic tokens before a skill's example values. Do not introduce a new palette, type scale, spacing scale, component library, or dependency to follow an example. Keep the pinned Frappe UI version. Again, I repeat, stick to Frappe UI conventions.

Apply the existing error placement rules in [`CLAUDE.md`](../CLAUDE.md#dashboard). Copy work does not change permission checks, resource behavior, or error handling.

Check the affected loading, empty, error, and disabled states. For visual or interaction changes, inspect the rendered view at a narrow width and check keyboard operation. Report any state or interaction you could not verify. Use `better-interface` only for a complete screen or flow review, and report any unavailable skill as a domain not reviewed.

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
