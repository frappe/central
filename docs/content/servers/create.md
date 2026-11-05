---
title: Create a server
description: Choose an image, SSH keys, network options, a region, and a plan, then create the server.
---

# Create a server

This page shows how to create a server from an image. To create a server from a snapshot, see [Restore a snapshot](/servers/snapshots#restore-a-snapshot).

## Before you begin

- You need the **Owner**, **Admin**, or **Developer** role.
- Your team needs a payment method. If it has none, the page shows **Add a payment method to create servers**. See [Payment methods](/billing/payment-methods).
- Add your public key in **Settings > SSH keys** if you want to sign in with SSH. You can also add a key on this page. See [Connect with SSH](/servers/access).

## Steps

1. Go to **Servers**. Click **New server**.
2. Type a **Name**, such as `pos-mumbai`.
3. Under **Image**, select **Frappe** or **Ubuntu**. See [Images](/servers/#images).
4. Select an **Image build**.
5. In **SSH keys**, select the keys that can sign in to the server.
6. Under **Network**, set the address and firewall switches. See [Network options](#network-options).
7. Under **Region**, select a region. You can also click the region on the map.
8. Under **Plan**, select a plan, or select **Custom** to choose the vCPU, memory, and disk.
9. Check the **Summary**. It shows the plan, the monthly price, the size, and the options that you selected.
10. Click **Create server**.

<Clip name="servers/create" alt="A recording of the New server page. The name pos-mumbai is typed, the Frappe image and an SSH key are selected, the firewall is turned on, and the 2 vCPU plan is selected. The summary shows the price." />

## Network options

| Switch | Effect |
| --- | --- |
| **Public IPv4 address** | Gives the server a public IPv4 address. It has a monthly price, which the switch shows. You can attach or detach it later. |
| **Public IPv6 address** | Gives the server a public IPv6 address. It is free. |
| **Enable firewall** | Allows only SSH, HTTP, and HTTPS from the internet. You can change the rules later. |

You can change all of these later on the **Networking** tab. See [Networking and firewall](/servers/networking).

## Result

The button shows each stage of the request: **Request accepted**, **Sent to the region**, and **Building your server**. When it shows **Server ready**, the server is `Active`.

## If the server is not created

| Message | What to do |
| --- | --- |
| **This region is at capacity** | Select another region, or try again later. |
| **You've reached your spending limit** | Terminate a server that you do not use, or contact support to raise your [spending limit](/billing/limits). |
| **We couldn't create this server** | Read the reason in the message. Correct the settings, then click **Create server** again. |
| **Couldn't create** and the server name | Click **Try again**, or click **Change configuration** to edit the settings. |

If a plan is grey with **Over your spending limit**, its price is more than your remaining limit.

## See also

- [Servers](/servers/)
- [Regions](/servers/regions)
- [Connect with SSH](/servers/access)
- [Resize, stop, and terminate](/servers/lifecycle)
