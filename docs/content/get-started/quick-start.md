---
title: Quick start
description: Sign up, create a Frappe server, and open your first site.
---

# Quick start

This guide shows how to create a server with Pilot and open your first site. It takes about 10 minutes.

## Before you begin

- A work email address. Frappe Cloud signs you in with a code that it sends to this address. There is no password.
- A payment method, such as a card. The console asks for it during setup.

## 1. Sign up

1. Open the Frappe Cloud console. Click **Create an account**.
2. Type your **Full name** and **Work email**. Click **Continue**.
3. Type the **Code** from the email.

The console opens a setup dialog with four steps:

| Step | What you do |
| --- | --- |
| **Create your team** | Type a **Team name**. A team holds your servers, members, and bill. |
| **Invite your team** | Add the email addresses of people who work with you. You can skip this step. |
| **Add a payment method** | Add a card. Your team pays for its servers at the end of each month. |
| **Get started** | Go to the console. |

Click **Skip** to leave a step for later. Click **Back** to go to an earlier step. You cannot go back to **Create your team**, because the team exists after that step.

<Screenshot name="get-started/onboarding" alt="The setup dialog on the Add a payment method step, with Back, Skip, and Add payment method at the bottom." />

## 2. Create a server

1. Go to **Servers**. Click **New server**.
2. Type a **Name**, such as `erp-production`.
3. Under **Image**, select **Frappe**. Select the newest **Image build**.
4. Under **Region**, select **Mumbai, India**.
5. Select a plan. You can [resize](/servers/lifecycle) the server later.
6. Click **Create server**.

<Clip name="servers/create" alt="A recording of the New server page. A name is typed, the Frappe image and an SSH key are selected, the firewall is turned on, and a plan is selected. The summary shows the monthly price." />

The button shows each stage: **Request accepted**, **Sent to the region**, and **Building your server**. When it shows **Server ready**, the console opens the server.

## 3. Check the server

The server page shows the status **Active** and live usage charts. The header shows the region, the plan, and the server's address.

<Screenshot name="get-started/server-running" alt="The erp-production server page. The status is Active. Charts show CPU, memory, network, and disk use for the last hour." />

## 4. Open your site

Click **Visit site** in the server header. Your site opens at an address in the region, such as `erp.bom.frappe.cloud`.

<Screenshot name="get-started/server-header" alt="The server header with the Actions menu and the Visit site button." />

If the image build has no site, the button is **Open Pilot**. Pilot opens, and you can [create a site](/pilot/sites) there.

## What next

- **[Create a staging server](/servers/create)**: try upgrades and new apps on a second server before production.

- **[Install apps](/pilot/apps)**: add ERPNext, Helpdesk, or your own app to the site.
- **[Add a domain](/pilot/domains)**: serve the site from your own domain.
- **[Connect with SSH](/servers/access)**: add a key and sign in to the server.
- **[Invite your team](/team/members)**: give other people access with a role.
