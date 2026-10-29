---
title: Networking and firewall
description: Server addresses, public IPv4 and IPv6, IPv4 internet access, and firewall rules.
---

# Networking and firewall

The **Networking** tab of a server shows its addresses, its firewall, and the domains that point to it. Go to **Servers**, click a server, then click **Networking**.

<Screenshot name="servers/networking" alt="The Networking tab of erp-production. The Addresses table lists a public IPv4, a public IPv6, and a private IPv6 address. Below it is the Firewall section." />

## Addresses

<Screenshot name="servers/addresses" alt="The Addresses section. Three rows: Public IPv4 203.0.113.24, Public IPv6, and Private IPv6, each with who can reach it." />

| Type | Reachable by | Price |
| --- | --- | --- |
| **Public IPv4** | Anyone on the internet | Monthly price for each region. The button shows the price. |
| **Public IPv6** | Anyone on the internet | Free |
| **Private IPv6** | Your servers in this region, and your WireGuard VPN devices when WireGuard VPN is on | Free |

Every server gets a private IPv6 address when it finishes setting up. Click an address to copy it.

### Attach a public address

1. In **Addresses**, click **Attach IPv4** or **Attach IPv6 · Free**.
2. For IPv4, read the price. Click **Attach IPv4**.

The IPv4 address is billed while it is attached. If the region is still applying the change, the address shows within a few minutes.

### Detach a public address

1. Open the row menu of the address. Click **Detach**.
2. Click **Detach** to confirm.

::: warning
A detached IPv4 address goes back to the region and its billing stops. You cannot get the same address back. A new IPv6 address can also be different from the old one.
:::

### IPv4 internet access

A server without a public IPv4 address cannot reach sites that have only IPv4 addresses. Turn on **IPv4 internet access** to let it reach them. The switch stays on while the server has a public IPv4 address.

## Firewall

The firewall controls who can connect to the server and where the server can connect. The region filters the traffic before it reaches the server.

<Screenshot name="servers/firewall" alt="The Firewall section of erp-production. Incoming rules allow SSH from 198.51.100.0/24 and ports 80 and 443 from anyone. The outgoing rule allows all traffic." />

When the firewall is off, every port is open to the internet. When you turn it on, it uses your saved rules. If there are no saved rules, it allows SSH, HTTP, and HTTPS in, and all connections out.

These connections are always allowed, so the web console keeps working:

- Your private network
- Your VPN devices
- Ping

### Change the rules

1. In **Firewall**, make sure the switch is on.
2. Under **Incoming** or **Outgoing**, click **Add incoming rule** or **Add outgoing rule**.
3. Select a **Service**, such as **SSH**, **HTTPS**, or **Custom TCP**.
4. For a custom service, type a **Port**. Use one port, a range such as `8000-8005`, or leave it empty for all ports.
5. In **Allowed from** or **Allowed to**, select **Anyone on the internet**, or select **Specific addresses**. Then type an IP address or range, such as `198.51.100.0/24`, and press Enter.
6. Click **Apply changes**. Confirm the change.

Click **Undo** to revert the last edit, or **Discard** to drop all unsaved edits. To delete a rule, click its delete icon.

### Use a preset or copy the rules

Click the options button next to the firewall switch:

| Option | Effect |
| --- | --- |
| **Use a preset** > **Web server** | Allow SSH, HTTP, and HTTPS from the internet, and all outgoing connections. |
| **Use a preset** > **SSH only** | Allow SSH from the internet, and all outgoing connections. |
| **Use a preset** > **Private only** | Block public incoming connections. Allow all outgoing connections. |
| **Copy to other servers** | Apply the same rules to other servers of your team. |

A preset replaces the rules in the editor. Click **Apply changes** to save them.

## Domains

The **Domains** section lists the site domains and custom domains that point to the server. Click the arrow next to a domain to open it. To add a domain, see [Domains and SSL](/pilot/domains).

::: info
Changing addresses and the firewall needs the **Owner**, **Admin**, or **Developer** role.
:::

## See also

- [Create a server](/servers/create)
- [Connect with SSH](/servers/access)
- [WireGuard VPN](/servers/wireguard)
- [Regions](/servers/regions)
- [Domains and SSL](/pilot/domains)
