# Central Spec

## IAM

- [IAM](IAM.md): architecture, identity, permissions, OAuth, and Atlas enforcement.
- [Execution Plan](EXECUTION_PLAN.md): ordered implementation and verification work.

Central authors identity and Team permissions. Each Atlas cluster consumes those
grants through OAuth and enforces them locally.

## Tunnel

- [Tunnel](TUNNEL.md): Central as the WireGuard hub, the `Register Atlas`
  orchestration, the per-Atlas scoped service user, and the host-exec runner for the
  hub scripts. Pairs with [atlas/spec/19-tunnel.md](../../atlas/spec/19-tunnel.md)
  (the Atlas-side lockdown + lockout-safe handshake).

Each Atlas management plane is reachable only over the tunnel; Central firewalls each
Atlas's public interface during a lockout-safe, Central-initiated registration.

## Billing

- [Atlas Integration](../../v2-billing-specs/atlas-integration/README.md): the
  Atlas → Billing Agent → Central workflow — lifecycle events, entitlement
  enforcement, metering, and the sync spine.

Atlas resources emit billing events to the per-cluster `press_billing_agent`
(in-process), which pushes them to Central's `billing` module where prices are
locked and invoices computed. The billing domain and the integration workflow
are both specced in [v2-billing-specs](../../v2-billing-specs/README.md).
