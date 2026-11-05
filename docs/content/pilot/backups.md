---
title: Backups and restore
description: Back up a site, schedule automated backups, keep a copy offsite, and restore a site from a backup.
---

# Backups and restore

A backup is a copy of a site at one point in time. Pilot stores each backup on the server. You can also keep a copy in object storage.

A backup has up to four files:

| File | Holds |
| --- | --- |
| Database | All the records of the site. |
| Public files | Files that anyone with the link can open. |
| Private files | Files that only signed-in users can open. |
| Config | The site config. |

A Pilot backup covers one site. To copy the whole server, take a [snapshot](/servers/snapshots) in the console.

## Back up a site now

1. Go to **Sites**. Click the site.
2. Click the **Backups** tab. Click **Back up now**.

Pilot opens the task page and shows each step. The backup shows in the **Backups** tab when the task finishes.

<Screenshot name="pilot/backups" alt="The Backups tab of erp.bom.frappe.cloud with one local backup and the Configure and Back up now buttons." />

You can also click **Back up now** in the site actions menu on the **Sites** page.

## Schedule automated backups

1. Go to the site page. Click the **Backups** tab.
2. Click **Enable**. If a schedule is already set, the button is **Configure**.
3. Select **Enable automated backups**.
4. Select the **Frequency**: **Daily**, **Weekly**, or **Monthly**. For a weekly or monthly backup, select the day.
5. Select the **Time**.
6. Select the **Retention** and the number of backups to keep.
7. Click **Save**.

<Screenshot name="pilot/backup-schedule" alt="The Configure automated backups dialog with a daily backup at 2:00 AM and GFS retention of 7 daily, 4 weekly, 12 monthly, and 10 yearly backups." />

| Retention | What it keeps |
| --- | --- |
| **GFS (daily / weekly / monthly / yearly)** | The newest backup of each day, week, month, and year, up to the number you set for each. |
| **FIFO (keep newest N)** | The newest backups, up to the number in **Backups to keep**. |

Pilot keeps manual backups until you delete them.

## Keep a copy offsite

Backups stay on the server until you connect object storage. If the server is lost, its local backups are lost with it.

1. Go to the site page. Click the **Backups** tab.
2. Click **Connect storage**. Pilot opens **Settings > General > Object storage settings**.
3. Select the **Provider** and the **Region**. Type the **Bucket**, the **Access Key**, and the **Secret Key**. Type the **Endpoint URL** if your provider needs one.
4. Click **Connect**.

The **Offsite** column shows **Uploaded** for a backup with a copy in object storage, and **Local only** for a backup on the server only.

## Download a backup

1. Go to the site page. Click the **Backups** tab.
2. Click the actions menu on the backup.
3. Click **Download Database**, **Download Public**, **Download Private**, or **Download Config**.

## Restore a backup

::: warning
A restore replaces the data of the target site with the data in the backup. Pilot does not take a backup before it restores. Click **Back up now** first if you need the current data.
:::

1. Go to the site page. Click the **Backups** tab.
2. Click the actions menu on the backup. Click **Restore…**.
3. Under **Restore into**, select the site. You can restore into a different site on the same bench.
4. Select the parts to restore: **Database**, **Public files**, or **Private files**.
5. Click **Restore**.

## Restore a site from another source

Use this to move a site to Frappe Cloud, or to copy data between sites.

1. Go to the site page. Click **Settings**.
2. Under **Danger**, click **Restore**.
3. Select the source and the parts to restore. Click **Restore**.

| Source | What you give |
| --- | --- |
| **Upload files** | The backup files from your computer. The database file usually ends in `.sql.gz`. The files archives end in `-files.tar` and `-private-files.tar`. |
| **Other site** | A site on the same bench. |
| **Remote site** | The address and **Administrator password** of a Frappe site on another host. Click **Get backups**, then select a **Backup**. |
| **Frappe Cloud v1** | The address of a site on Frappe Cloud v1. Click **Connect**. Click **Open Frappe Cloud** and type the pass code there to allow access. Then select a backup, or click **Take new backup**. |

Select **Skip failing patches** if the backup comes from an older version and a database patch fails during the restore.

## Delete a backup

1. Go to the site page. Click the **Backups** tab.
2. Click the actions menu on the backup. Click **Delete backup**.
3. Click **Delete** to confirm. You cannot undo this.

## See also

- [Sites](/pilot/sites)
- [Snapshots](/servers/snapshots)
- [Updates and migrations](/pilot/updates)
- [Logs and tasks](/pilot/logs)
