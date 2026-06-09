# Execution Plan

## 1. Complete The Capability Catalog

- Add `vm:snapshot`, `vm:rebuild`, and `vm:clone` capabilities.
- Assign them to the standard Team roles.
- Keep Viewer read-only and Billing limited to billing plus read access.
- Export fixtures and verify Central's resolved grants.

## 2. Attribute Atlas Resources

- Add immutable, indexed `team` fields to VMs and snapshots.
- Require an explicit authorized Team for VM creation.
- Inherit Team attribution for snapshots and derived resources.
- Reject cross-Team clone and rebuild operations.
- Keep legacy unattributed resources operator-only.

Verification:

- A Developer can create a VM in an authorized Team.
- The same user cannot create or derive a VM in another Team.
- Snapshot Team attribution matches its VM.

## 3. Scope Resource Reads

- Add `permission_query_conditions` for VM and snapshot lists.
- Add `has_permission` checks for direct document reads.
- Scope linked Tasks through their VM.
- Deny reads when grants are missing or malformed.
- Use `frappe.qb` for joins or transformed multi-table queries.

Verification:

- A Viewer sees resources only for Teams with `vm:view`.
- Direct document access follows the same boundary as list access.
- `System Manager` retains full visibility.

## 4. Enforce VM Actions

- Apply the authorization decorator to loaded-VM actions.
- Use explicit checks for create, clone, and other cross-resource operations.
- Require both capabilities for composite actions such as restart.
- Preserve existing VM lifecycle validation and error behavior.

Verification:

- Viewer actions are denied.
- Developer actions follow the capability mapping.
- Cross-Team actions are denied.
- `System Manager` remains the sole bypass.

## 5. Add Team Routes

- Add Team-scoped machine list and detail routes.
- Preserve the Central OAuth login flow.
- Ensure route parameters cannot expand the session grant set.

## 6. Prove The Flow

Test with:

- A user who owns Team A
- The same user as Developer in Team B
- A second user as Viewer in Team B

1. Sign in to Atlas through Central OAuth.
2. Inspect `atlas.atlas.api.iam.session_grants`.
3. Check allowed and denied cases with
   `atlas.atlas.api.iam.check_session_capability`.
4. Verify list filtering and direct document access for each user.
5. Run allowed, denied, and cross-Team VM actions.
6. Open the Team-scoped list and detail routes.

## Completion Criteria

- Every Atlas VM and snapshot has an authoritative Team boundary.
- Reads and mutations enforce the same capability model.
- OAuth grants are inspectable without being mutable.
- Automated tests cover allowed, denied, malformed-grant, cross-Team, and
  `System Manager` cases.
- The manual OAuth-to-resource flow is reproducible on separate Central and
  Atlas sites.
