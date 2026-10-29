# Roles and permissions

A role is a named set of permissions that you give to a team member. Every team has 5 system roles. You can also create custom roles for your team.

## System roles

The system roles are the same in every team. You cannot change or delete them.

| Role | What the member can do |
| --- | --- |
| Owner | Everything, including archive the team. A team has exactly one Owner. |
| Admin | Everything except archive the team: manage members and roles, edit the team, manage billing, and operate servers and services. |
| Developer | Create and operate servers, manage Team SSH keys, open the server web console, and manage add-on services. No billing and no member management. |
| Billing | View and manage billing. View servers and manage add-on services. |
| Viewer | View servers, regions, and add-on services. No changes. |

## Permissions by role

| Permission | Owner | Admin | Developer | Billing | Viewer |
| --- | :-: | :-: | :-: | :-: | :-: |
| Archive the team | ✓ | | | | |
| Rename the team and change its logo | ✓ | ✓ | | | |
| Invite, change, and remove members | ✓ | ✓ | | | |
| View invoices, usage, and billing details | ✓ | ✓ | | ✓ | |
| Add credit, change payment methods, and update billing details | ✓ | ✓ | | ✓ | |
| View servers, their status, and their metrics | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create servers | ✓ | ✓ | ✓ | | |
| Start, stop, and restart servers | ✓ | ✓ | ✓ | | |
| Resize, rebuild, or rename servers | ✓ | ✓ | ✓ | | |
| Change the firewall and public addresses | ✓ | ✓ | ✓ | | |
| Create and restore snapshots | ✓ | ✓ | ✓ | | |
| Terminate servers | ✓ | ✓ | ✓ | | |
| Manage Team SSH keys | ✓ | ✓ | ✓ | | |
| Open the server web console | ✓ | ✓ | ✓ | | |
| View add-on services | ✓ | ✓ | ✓ | ✓ | ✓ |
| Subscribe to and manage add-on services | ✓ | ✓ | ✓ | ✓ | |

To see the exact permissions of a role, go to **Team**, click **Roles**, and click the role.

<Screenshot name="team/role-capabilities" alt="The Roles tab with the Developer role open, showing its permissions grouped under Services and Servers" />

## Roles on one server or site

You can give a role on **All resources** or on one server or site. Select the resource when you [invite a member](/team/members#invite-members) or in **Manage access**.

A role on one server gives only the permissions that act on that server: view, start and stop, firewall, resize, snapshot, terminate, and web console. All other permissions come only from a role on **All resources**. For example, a Developer on one server can stop that server, but cannot create a server or change the Team SSH keys.

## Create a custom role

Create a custom role when no system role fits, such as server operations without terminate.

1. Go to **Team**. Click **Roles**.
2. Click **New role**.
3. Type a **Role name**.
4. Select the permissions. Frappe Cloud adds the view permissions that a selected permission needs.
5. Click **Create role**.

<Screenshot name="team/new-role" alt="The New custom role dialog with a role name field and permission checkboxes grouped by Billing, Team, Services, and Servers" />

You can only give permissions that you hold yourself. You cannot edit a custom role after you create it. To change it, create a new role, move the members to it, and delete the old one.

## Delete a custom role

1. Go to **Team**. Click **Roles**.
2. Click the **⋮** menu on the custom role. Click **Delete**.

You cannot delete a role that a member holds or that a pending invitation uses. Change those members' access and revoke those invitations first. You cannot delete a system role.

## Transfer ownership

Only the Owner can transfer ownership. The new Owner must be an active member of the team.

1. Go to **Team**. Click the **⋮** menu on the new Owner's row.
2. Click **Transfer ownership**.
3. Type the member's name to confirm.
4. Click **Transfer ownership**.

The member becomes the Owner, and their other roles are removed. You become an Admin. Only the new Owner can transfer ownership back.

You cannot remove the Owner from the team. To remove the current Owner, transfer ownership to another member first.

## See also

- [Members and invitations](/team/members)
- [Team settings](/team/settings)
- [Credits and spend limits](/billing/limits)
- [Connect with SSH](/servers/access)
