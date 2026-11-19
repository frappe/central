---
title: Updates and migrations
description: Update the apps on a bench. Pilot backs up and migrates each site, and helps you recover if an update fails.
---

# Updates and migrations

An update moves the apps on a bench to newer code. A migration then changes the database of each site to match the new code. Pilot runs both as one update, with a recovery backup for each site.

## How an update runs

Pilot runs an update in stages. Each stage is a task that you can watch.

| Stage | What Pilot does |
| --- | --- |
| Prepare | Records the settings of each affected site and puts the site in maintenance mode. |
| Back up | Takes a recovery backup of each affected site. |
| Update | Gets the new app code, installs its dependencies, and builds the assets. |
| Migrate | Migrates each affected site, one after the other. |
| Complete | Gives each site back its maintenance mode and background job settings. |

Pilot migrates a site only when the new code needs it, for example when it adds a patch or changes a doctype. If no app needs a migration, Pilot only updates the code, builds the assets, and restarts the processes.

Recovery backups are separate from your site backups. They do not show in the **Backups** tab.

## Update apps

When an app has newer code, Pilot shows **Update available** in the header of the **Sites**, **Marketplace**, and **Updates** pages.

1. Click **Update available**. The **Updates** dialog lists each app with its current and new version.
2. Select the apps to update, or click **Select all**.
3. Keep **Take backup of sites** selected. Pilot shows this option when the update migrates sites.
4. Click **Update** or **Update all**.

Pilot opens the update page. It shows each stage, the target apps, and the sites. While an update runs, the header button shows its progress. Click it to open the update page.

If you clear **Take backup of sites**, Pilot takes no recovery backup. You cannot restore the sites if the migration fails.

## Follow updates

Go to **Updates**. The page lists every update and migration. Use the tabs to filter the list: **All**, **Running**, **Attention**, **Completed**, and **Reverted**.

Click an update to open its page.

## Recover from a failed update

If a stage fails, the update stops and shows in **Attention**. The update page shows the error. If a database patch failed, it shows the **Failing patch**. Click **Show error output** to read the full output.

Choose one recovery action:

| Action | What it does |
| --- | --- |
| **Retry update** | Runs the update again from the failed step. Sites that finished are skipped. Fix the cause first. |
| **Skip patch** | Marks the failing patch as done on the failed site without running it, then continues. You cannot undo this. |
| **Restore backup** | Returns the apps to their previous versions. Migrated sites get their data back from the recovery backup. Sites that were not migrated yet stay as they are. |

Each action asks you to confirm. A completed restore shows in **Reverted**. If the restore itself fails, fix the cause and click **Restore backup** again.

::: warning
Use **Skip patch** only when you know the patch is safe to skip. The data change in the patch does not happen on that site.
:::

## Migrate one site

To run the migrations of one site again, go to the site page. Click **Settings**. Under **Danger**, click **Migrate**.

This migration takes no recovery backup, and you cannot revert it. Read [Sites](/pilot/sites#migrate-a-site).

## Update Pilot

Pilot itself also gets updates. Go to the Pilot menu. Click **Settings**. In **General**, the **Pilot Version** row shows your version.

1. Click **Update**. Pilot checks for a newer version.
2. If a version is available, click **Update to `<version>`**.

Pilot updates itself and restarts its own service. Your sites keep running.

## See also

- [Apps](/pilot/apps)
- [Backups and restore](/pilot/backups)
- [Logs and tasks](/pilot/logs)
- [Sites](/pilot/sites)
