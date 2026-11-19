# Team settings

Change the team name and logo, switch between teams, create a team, or archive a team. Team settings are on the **Team** tab of the settings dialog.

## Open team settings

Go to **Team**. Click the pencil icon next to the team name. The settings dialog opens on the **Team** tab.

<Screenshot name="team/settings" alt="The Team tab of the settings dialog with the logo, the team name, and the Archive team section" />

::: info
You need the Owner or Admin role to change the name or the logo. Only the Owner can archive the team.
:::

## Rename the team

1. Open team settings.
2. Change the **Team name**.
3. Click **Save**, or press Enter.

The new name shows in the team switcher and on the **Team** page for every member.

## Change the logo

1. Open team settings.
2. Click the logo under **Logo**.
3. Click **Upload a logo** and select an image. To remove the logo, click **Remove logo**.

Without a logo, the team shows the first letter of its name.

## Switch teams

You can belong to more than one team. Each team has its own servers, members, and billing.

1. Click the team name at the top of the sidebar.
2. Click the team to open.

The console reloads on that team. When you belong to more than 6 teams, the list has a search box.

## Create a team

1. Click the team name at the top of the sidebar.
2. Click **Create team**.
3. Type a **Team name**.
4. Click **Create team**.

<Screenshot name="team/create" alt="The Create a team dialog with a Team name field" />

You are the Owner of the team you create. The new team has its own billing, so add billing details before you create servers in it. See [Payment methods](/billing/payment-methods).

## Archive the team

Archive a team when you no longer use it. Every member loses access. Invoices and records are kept.

Before you can archive, the dialog checks that:

- All servers are terminated.
- No paid snapshots remain.
- No bucket subscriptions or other paid add-ons are billing.
- No invoices are unpaid.
- This month's charges can be collected, so the team has a payment method if it owes money.

<Screenshot name="team/archive" alt="The Archive team dialog with a checklist: 12 servers not terminated and 2 bucket subscriptions still billing" />

Each failed check has a button that opens the page where you fix it.

1. Open team settings.
2. Under **Archive team**, click **Archive**.
3. Fix each failed check.
4. Type the team name to confirm.
5. Click **Archive team**.

::: warning
Archiving forfeits any credit left in the team's wallet. The dialog shows the amount. To use an archived team again, contact support.
:::

## See also

- [Members and invitations](/team/members)
- [Roles and permissions](/team/roles)
- [How billing works](/billing/)
- [Resize, stop, and terminate](/servers/lifecycle)
