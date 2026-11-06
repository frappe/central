# Billing change checklist

Read the root [CLAUDE.md](../../CLAUDE.md) first. This file adds the checks for a change under `central/billing/`. A billing defect charges a customer the wrong amount, loses money, or stops a server that was paid for. Apply every check before you commit.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the money paths, the ledger, and the state machines.

## Before you change a contract

- Find every caller of a function, a whitelisted method, or a DocType field that you change. Search `central/` and `dashboard/src/`. Frappe passes the request body as keyword arguments, so a dashboard caller that sends a removed argument fails only at runtime.
- When you move a rule into a shared function, list each path that calls it. Put the rule in the shared function only when it is correct for all of them.
- When you remove a behavior, find the code that replaces it and the code that calls the replacement. A function that nothing calls does not run.

## Fix the sibling path

The same job often exists in more than one path. When you fix one, find and fix the others in the same commit, or merge them into one function.

| Job | Paths to check together |
|---|---|
| Settle a gateway payment | Invoice charge, on-session checkout, top-up order, webhook, reconciliation |
| Handle a short or a surplus payment | Invoice settlement, top-up order |
| Reconcile with a gateway | Payment attempt, checkout attempt, captured attempt, top-up order |
| Gate added spend | New server, preset resize, composed resize, service subscription |
| Change account standing | Dunning suspend, payment restore, operator action |

## Use one predicate for one business term

- Define a term such as "owes money", "in flight", or "settled" once, as a named constant or function, for example `UNSETTLED` or `has_overdue_invoice`. Use it everywhere.
- Do not write an inline status tuple in a billing condition.
- Make the docstring say the same thing as the predicate. When a docstring says "owes nothing else" and the code checks only `Overdue`, one of them is wrong.

## Isolate each item in a sweep

A scheduled job, a dunning run, or a reconciliation run processes many records. One bad record must not stop the rest, and must not roll back the work already done.

- Run each item under its own savepoint. On any `Exception`, roll back to the savepoint, call `frappe.log_error` with the reference document, and continue.
- Do not catch only `frappe.ValidationError` in a sweep. A database error, a `KeyError`, or a gateway timeout also stops the run.
- Guard every gateway call in a sweep. An adapter raises `GatewayUnsupported`, `GatewayTimeout`, or `GatewayError`. Return an unresolved result for that item instead of raising.

## Never let a side effect roll back a payment

A hook such as `Invoice.on_update` runs inside the transaction that records the payment. When a side effect in that hook raises, the gateway keeps the money and Central loses the settlement.

- Isolate each side effect of a payment, such as a standing change, a server start, or a notification, under a savepoint, or enqueue it after commit.
- Log a failed side effect against its document so an operator can act on it.

## Trace a state before you reuse it

Before you move a record to an existing state, find every query that reads that state. For example, `Captured` is in `_IN_FLIGHT`, so a captured attempt blocks every later payment on its invoice. Add a new state or a new transition when the existing meaning does not fit.

## Test the claim

- Write each commit subject as a claim, and write a test that fails without the change.
- Add the negative and sibling cases: a second invoice that is `Open`, a plan that includes a `Transfer` row, an overpaid top-up, a PayPal attempt, an unexpected exception type.
- For a sweep, add a test where one item raises a plain `Exception` and the other items still complete.
- For a payment side effect, add a test where the side effect raises and the invoice is still `Paid`.
- Patch `central.billing.gateways.registry.get_adapter` in a test. CI has no gateway keys.

## Validation

Run the guard checks and the focused tests before you push. From `apps/central`:

```sh
PATH=~/.local/share/central-lint/venv/bin:$PATH python ~/.claude/skills/central-guard-check/guard_check.py
```

Run `/code-review` on the diff, and run the `central-billing-bug-review` probes for a change to a money path.
