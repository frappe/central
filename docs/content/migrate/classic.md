---
title: Migrate from Frappe Cloud Classic
description: Move a site from Frappe Cloud Classic to a server of your own, with its database, files, and domain.
---

# Migrate a site from Frappe Cloud Classic

This guide shows how to move a site from Frappe Cloud Classic to a server on Frappe Cloud. Frappe Cloud Classic is the earlier Frappe Cloud at `cloud.frappe.io`. Pilot calls it **Frappe Cloud v1**.

Pilot reads a backup of the Classic site and restores it into a site on your server. The Classic site keeps running and does not change. You can do a test migration first, and do the final one when you are ready.

<Clip name="migrate/connect" alt="A recording of the Restore Site dialog in Pilot. The Frappe Cloud v1 source is selected, the address of the Classic site is typed, and Connect is clicked. A pass code shows. After approval, the list of backups shows and the newest backup is selected." />

## Before you begin

- The Classic site runs Frappe version 16. Update an older site on Frappe Cloud Classic first.
- You can sign in to Frappe Cloud Classic as a member of the team that owns the site.
- You have a server with the **Frappe** image, version 16. Read [Create a server](/servers/create).
- You know which apps the Classic site has. Open the site on Frappe Cloud Classic to see the list.

## 1. Prepare the new site

The restore replaces the data of a site that exists on your server. Create that site first.

1. Open Pilot. In the console, open the server and click **Open Pilot**.
2. Use the site that came with the server, or [create a site](/pilot/sites).
3. Install each app that the Classic site has. Read [Apps](/pilot/apps).

::: warning
Install the same apps before you restore. The restore runs a migration, and the migration fails when the database needs an app that the server does not have.
:::

For a private app, [connect GitHub](/pilot/github) first.

## 2. Connect to the Classic site

1. In Pilot, go to **Sites**. Click the site.
2. Click the **Settings** tab. Under **Danger**, click **Restore**.
3. Click **Frappe Cloud v1**.
4. In **Site on Frappe Cloud**, type the address of the Classic site, such as `erp.example.com`. Click **Connect**.

<Screenshot name="migrate/pass-code" alt="The Restore Site dialog on the Frappe Cloud v1 source. It shows an 8-character pass code, the Open Frappe Cloud and Cancel buttons, and the text Waiting for approval." />

Pilot shows a pass code of 8 characters.

5. Click **Open Frappe Cloud**. Frappe Cloud Classic opens in a new tab. Sign in if it asks.
6. In the **Authorize backup access** dialog, check the **Site**. Type the code in **Pass code shown in Pilot**.
7. Click **Approve request**.

Go back to Pilot. The dialog changes to the list of backups in a few seconds.

| Limit | Value |
| --- | --- |
| Time to approve a request | 10 minutes |
| Wrong pass codes before the request is rejected | 5 |
| Access to the backups after approval | 12 hours |

Pilot gets access only to the backups of this one site. It cannot change the Classic site. To stop the access early, click **Change site** in the dialog.

If Frappe Cloud Classic shows **You don't have access to allow this request**, ask the owner of the Classic site to open the link and approve.

## 3. Select a backup

The dialog lists the backups of the Classic site that include files and are stored offsite. Each row shows the date and the total size. The newest backup is selected.

<Screenshot name="migrate/backups" alt="The Restore Site dialog with the backups of erp.contrail.example. Three backups show their date and size, and the newest is selected. Below are the Take new backup button and the checkboxes for the parts to restore." />

- For a test migration, keep the selected backup.
- For the final migration, click **Take new backup**. Pilot asks Frappe Cloud Classic for a fresh backup and shows **Backing up** until it is ready. Click **View job** to follow the backup on Frappe Cloud Classic.

::: info
Data that users add to the Classic site after the backup does not move. For the final migration, ask your users to stop work on the Classic site before you click **Take new backup**.
:::

## 4. Restore

::: warning
The restore deletes the database of the new site and replaces it with the backup. Pilot does not take a backup of the new site first. You cannot undo this.
:::

1. Keep **Database**, **Public files**, **Private files**, and **Site config** selected.
2. Click **Restore**.

Pilot opens the task page and shows each step. The new site is in maintenance mode until the task finishes.

The restore brings these with it:

- All records, users, and passwords. Your users sign in as they did on the Classic site.
- Public and private files.
- The encryption key, so saved passwords and API secrets on the site still work.
- The settings in the site config, except the settings that belong to the server, such as the database, the domains, and the scheduler state.

Pilot ends its access to the Classic site when the restore starts. To restore again, connect again.

If the task fails, the site stays in maintenance mode. Read the error on the task page, fix the cause, and restore again. Select **Skip failing patches** only when a database patch fails and you know that the site can work without it.

## 5. Check the new site

Open the new site at its Frappe Cloud address, such as `erp.bom.frappe.cloud`. Sign in with a user of the Classic site.

Check what your team uses each day:

- Recent documents and the files attached to them.
- Print formats and reports.
- Email accounts, and one outgoing email.
- Integrations that call the site or that the site calls. Update each one that uses the address of the site.
- Scheduled jobs. Read [Logs and tasks](/pilot/logs).

Set up [automated backups](/pilot/backups#schedule-automated-backups) on the new site. The backup schedule of the Classic site does not move.

## 6. Move the domain

The domains of the Classic site do not move with the restore. Add each one to the new site.

Follow [Domains and SSL](/pilot/domains) for each domain. At your DNS provider, change the record that points the domain to Frappe Cloud Classic. Visitors reach the Classic site until the DNS change spreads, so keep it in place during that time.

## After the migration

The Classic site still runs, and Frappe Cloud Classic still bills you for it. Data does not sync between the two sites, so let users work only on the new one. Archive the Classic site when you no longer need it as a fallback.

## Fix a problem

| What you see | What to do |
| --- | --- |
| The pass code shows, but Frappe Cloud Classic has no request to approve. | Check the address that you typed. Click **Cancel**, then connect with the correct address. |
| **The request for … is expired. Connect again.** | The 10 minutes to approve are over. Click **Connect** again. |
| **The request for … is rejected. Connect again.** | The pass code was wrong 5 times. Click **Connect** to get a new code. |
| **No backups yet. Take a new backup.** | The Classic site has no offsite backup with files. Click **Take new backup**. |
| **Could not reach Frappe Cloud.** | Try again in a few minutes. |
| The task fails at **Migrating the site...** | An app is missing or has a different version. Install the apps of the Classic site, then restore again. |

If the problem remains, [contact support](/help/support).

## What next

- **[Backups and restore](/pilot/backups)**: schedule backups and keep a copy offsite.
- **[Domains and SSL](/pilot/domains)**: add more domains to the site.
- **[Members and invitations](/team/members)**: give your team access to the server.
- **[Snapshots](/servers/snapshots)**: copy the whole server before a risky change.
