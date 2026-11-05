---
title: Resize, stop, and terminate
description: Start, stop, restart, rename, resize, protect, and terminate a server.
---

# Resize, stop, and terminate

This page shows how to change the power state, size, and name of a server, and how to delete it. You find these actions in the **Actions** menu and on the **Settings** tab of the server.

::: info
These actions need the **Owner**, **Admin**, or **Developer** role. The console shows only the actions that are valid for the current status of the server.
:::

## The Actions menu

Open the server. Click **Actions** in the header.

<Screenshot name="servers/actions" alt="The erp-production server page with the Actions menu open. It lists Open server, Web console, Stop, Restart, Take snapshot, Rename, and Copy server ID." />

| Action | Effect |
| --- | --- |
| **Open server** | Signs you in to Pilot on a Frappe server. |
| **Web console** | Opens a root shell or a serial console. See [Connect with SSH](/servers/access#sign-in-without-a-key). |
| **Start** | Starts a server that is `Stopped`, `Paused`, or `Broken`. |
| **Stop** | Turns off a running server. |
| **Restart** | Restarts a running server. |
| **Take snapshot** | Copies the disk. See [Snapshots](/servers/snapshots). |
| **Rename** | Changes the name of the server. |
| **Copy server ID** | Copies the server ID, for a support request. |

## Stop, start, or restart

1. Click **Actions**, then **Stop** or **Restart**.
2. Click **Stop** or **Restart** to confirm.

Sites on the server are unavailable while it is stopped and during a restart. To start the server, click **Actions**, then **Start**. Start needs no confirmation.

## Resize a server

A resize changes the vCPU, memory, and disk of the server.

<Screenshot name="servers/settings" alt="The Settings tab of erp-production, with Resize server and Terminate server." />

1. Open the server. Click **Settings**. Under **Resize server**, click **Resize**.
2. Under **Storage**, select **Keep current** to keep the disk size, or select **Increase storage**.
3. Select a plan, or select **Custom**.
4. Click **Resize**.

The status shows `Resizing` until the change is done. A CPU or memory change restarts the server. A larger disk does not.

::: warning
You cannot decrease the disk size later. If the server has an older rate, the dialog shows **Resizing will change your rate**. The new plan uses current prices, and you cannot get the old rate back.
:::

## Turn on termination protection

Termination protection stops anyone from terminating the server by mistake.

1. Open the server.
2. Click the lock button next to **Actions**. Its tooltip is **Turn on termination protection**.

To turn it off, click the lock button again. If the region does not confirm the change, the console shows **Termination protection wasn't changed** and the setting stays as it was.

## Terminate a server

Terminate deletes the server and all data on its disk. The site addresses and custom domains that point to the server stop working. You cannot undo this.

1. Open the server. Click **Settings**. Under **Terminate server**, click **Terminate**.
2. Read the list of addresses that will stop working.
3. To keep a copy of the disk, select **Take a final snapshot first**.
4. Type the server name to confirm.
5. Click **Yes, terminate**.

<Screenshot name="servers/terminate" alt="The Terminate server dialog for erp-staging. It lists erp-staging.bom.frappe.cloud as a site that will become unavailable, offers a final snapshot, and asks you to type the server name." />

If termination protection is on, the dialog tells you to turn it off first. A final snapshot follows the [snapshot prices](/servers/snapshots#cost).

## See also

- [Servers](/servers/)
- [Monitor usage](/servers/usage)
- [Snapshots](/servers/snapshots)
- [Credits and spend limits](/billing/limits)
