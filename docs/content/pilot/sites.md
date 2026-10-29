---
title: Sites
description: Create a site in Pilot, open it, and change its settings. Rename, migrate, reset, or drop a site.
---

# Sites

A site is one Frappe installation with its own database, files, and domain. A bench can run many sites, and each site uses some of the apps on the bench.

For example, the Contrail Coffee bench runs two sites:

| Site | Apps |
| --- | --- |
| `erp.bom.frappe.cloud` | Frappe, ERPNext |
| `chat.bom.frappe.cloud` | Frappe, Raven |

Sites on a server share its CPU, memory, and disk. A new site has no extra cost. When a site needs its own resources, its own update schedule, or its own snapshots, [create a server](/servers/create) for it.

## Site states

| State | Meaning |
| --- | --- |
| **Active** | The site is ready. Pilot does not show a state on an active site card. |
| **Creating** | Pilot is creating or reinstalling the site. |
| **Paused** | The site directory or its config file is missing. |
| **Broken** | The site exists, but Pilot cannot read it correctly. |

## Create a site

1. Go to **Sites**. Click **New site**.
2. Type a name in **Site name**, such as `erp`. Pilot adds the region domain, such as `.bom.frappe.cloud`. **Web address** shows the full address.
3. Under **Choose apps**, select the apps to install, such as ERPNext. The list shows the apps on the bench.
4. Click **Create Site**.

<Screenshot name="pilot/new-site" alt="The New Site dialog. The site name is learn, the web address is learn.bom.frappe.cloud, and the app list shows ERPNext, HR & Payroll, Helpdesk, and more." />

Pilot opens the task page and shows each step. The site shows **Creating** until the task finishes. Read [Logs and tasks](/pilot/logs).

To install an app that is not on the bench yet, add it from the **Marketplace** after you create the site. Read [Apps](/pilot/apps).

## Finish the setup wizard

A new site starts with the Frappe setup wizard. On the site page, the header button shows **Setup site** until you finish the wizard.

1. Go to **Sites**. Click the site.
2. Click **Setup site**. The setup wizard opens in a new tab.
3. Complete the wizard.

Pilot shows **Site setup is complete** when the wizard finishes. The header button then shows **Visit site**.

## Open a site

On the site page, click **Visit site**. The site Desk opens in a new tab with your current browser session on that site.

To sign in as the Administrator user, click the actions menu on the site page. Click **Login as admin**. This replaces any other session you have on that site.

The site actions menu on the **Sites** page has the same actions, plus **Back up now**, **View analytics**, and **View jobs**.

## Site page

Click a site on the **Sites** page. The site page has five tabs.

<Screenshot name="pilot/site-detail" alt="The erp.bom.frappe.cloud site page on the Apps tab, with Frappe and ERPNext, and the View analytics and Install app buttons." />

| Tab | What it shows |
| --- | --- |
| **Apps** | The apps on the site. Install, switch branch, or uninstall. Read [Apps](/pilot/apps). |
| **Backups** | The backups of the site and the backup schedule. Read [Backups and restore](/pilot/backups). |
| **Config** | The keys in the site config. Click **Add config** to add a key, or use the row menu to edit or remove one. |
| **Activity** | The actions that people and Pilot took on the site. |
| **Settings** | General switches, domains, actions, and the danger zone. |

## Change site settings

Go to the site page. Click the **Settings** tab.

| Section | Item | What it does |
| --- | --- | --- |
| **General** | **Maintenance mode** | Visitors see a "back soon" page while you work. |
| **General** | **Background jobs** | Runs scheduled emails, reports, and automations. Turn it off to pause the scheduler. |
| **General** | **Developer mode** | Lets developers customize doctypes on the site. It shows only when **Allow developer mode** is on in **Settings > General**. |
| **Domains** | | The domains of the site. Read [Domains and SSL](/pilot/domains). |
| **Actions** | **Clear cache** | Clears the site cache. Use it when something looks out of date. |
| **Actions** | **Build assets** | Builds the JS and CSS for the apps of the site again. |
| **Actions** | **Refresh usage** | Measures the disk use of the sites again. Pilot also measures it every 6 hours. |

## Rename a site

The site is offline for a moment while Pilot renames it.

1. Go to the site page. Click **Settings**.
2. Under **Danger**, click **Rename**.
3. Type the **New name**.
4. Keep **Keep `<old name>` working as well** selected if visitors still use the old address.
5. Click **Rename**.

## Migrate a site

A migration runs the pending database migrations on the site. The site can go down while it runs. An app update migrates sites for you, so use this action only to run a migration again.

1. Go to the site page. Click **Settings**.
2. Under **Danger**, click **Migrate**. Click **Migrate** again to confirm.

A migration from this action takes no recovery backup and you cannot revert it. Read [Updates and migrations](/pilot/updates).

## Reset a site

A reset deletes every record on the site. The database goes back to a fresh install. The installed apps stay. You cannot undo this.

1. Go to the site page. Click **Settings**.
2. Under **Danger**, click **Reset**.
3. Type the site name to confirm. Click **Reset site**.

## Drop a site

::: warning
Dropping a site deletes its database and every file of the site. You cannot undo this. Pilot keeps the existing backups for 30 days.
:::

1. Go to the site page. Click **Settings**.
2. Under **Danger**, click **Drop**.
3. Type the site name to confirm.
4. Keep **Take a backup before dropping** selected to take a last backup.
5. Click **Drop site**.

## Limits

- All sites on a server share its CPU, memory, and disk. To get more, [resize the server](/servers/lifecycle).
- All sites on a bench use the same version of each app.

## See also

- [Apps](/pilot/apps)
- [Domains and SSL](/pilot/domains)
- [Backups and restore](/pilot/backups)
- [Logs and tasks](/pilot/logs)
