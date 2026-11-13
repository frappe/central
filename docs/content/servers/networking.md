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

When the firewall is off, every port is open to the internet. When you turn it on, it uses your saved rules. A new server starts with these incoming rules, and all connections out:

| Rule | Why |
| --- | --- |
| **All traffic** from **Frappe Cloud network** (`fdaa::/16`) | The Frappe Cloud proxy that serves your sites and your other servers in the region connect through it. |
| **Ping** from anyone | IPv6 needs ICMP to find neighbours and the path size. |
| **SSH**, **HTTP**, and **HTTPS** from anyone | Sign in, and serve sites directly. |

You can remove any of these rules. If you remove **Frappe Cloud network**, your sites stop working through Frappe Cloud. The web console still works. The console warns you before it applies such a change.

The firewall shows each address range by a name. Hover over a name to see the range.

| Name | Range | Who it is |
| --- | --- | --- |
| **Any IPv4** | `0.0.0.0/0` | Anyone on the internet, over IPv4. |
| **Any IPv6** | `::/0` | Anyone on the internet, over IPv6. |
| **Frappe Cloud network** | `fdaa::/16` | The Frappe Cloud proxy and your other servers in the region. |
| **Your VPN devices** | `fdac::/16` | The devices your team added under WireGuard VPN. |

The firewall does not limit who opens a site that the Frappe Cloud proxy serves. The proxy connects to the server from the Frappe Cloud network for every visitor.

The firewall also filters [WireGuard VPN devices](/servers/wireguard). To let a device in, add a rule and select the device by its name in **Allowed from**.

### Change the rules

1. In **Firewall**, make sure the switch is on.
2. Under **Incoming** or **Outgoing**, click **Add incoming rule** or **Add outgoing rule**.
3. Select a **Service**, such as **SSH**, **HTTPS**, or **Custom TCP**.
4. For a custom service, type a **Port**. Use one port, a range such as `8000-8005`, or leave it empty for all ports.
5. Click **Allowed from** or **Allowed to** and select who the rule allows, such as **Any IPv4**, **Your VPN devices**, or a WireGuard VPN device. To allow another address, type an IP address or range, such as `198.51.100.0/24`, then press Enter. Click the cross on a name to remove it.
6. Click **Apply changes**. Confirm the change.

Click **Undo** to revert the last edit, or **Discard** to drop all unsaved edits. To delete a rule, click its delete icon.

### Use rulesets

A firewall ruleset holds rules that you define once and apply to many servers. When you change a ruleset, every server that uses it gets the new rules.

A server can use more than one ruleset. The server then allows what any of its rulesets allows. For example, apply a **Base** ruleset to every server, and add a **Proxy** ruleset only to the servers that need its extra rules.

1. Open **Settings**, then click **Firewall rulesets**.
2. Click **Add ruleset**. Type a **Name**, change the rules, then click **Create ruleset**.
3. Open the **Networking** tab of a server. In **Firewall**, click **Apply ruleset**.
4. Select the checkbox of each ruleset the server must use. Click a name to see its rules. Then click **Apply**.

The server now shows the rules of its rulesets, and each rule shows the ruleset it comes from. You cannot change these rules on the server.

| To | Do this |
| --- | --- |
| Remove one ruleset | Click the cross on its name above the rules. |
| Change which rulesets the server uses | Click **Change rulesets**. |
| Change the rules for this server only | Remove every ruleset. The server keeps the rules as its own, and you can change them. |

The rulesets of one server can hold 50 addresses together. You can delete a ruleset only when no server uses it. Changing rulesets needs the network capability on the whole team, not on one server.

### Use built-in rules

The **Apply ruleset** dialog also lists three built-in rule sets. Select one and click **Use these rules**. The console copies the rules to the editor of this server. Review them, then click **Apply changes**.

| Built-in | Effect |
| --- | --- |
| **Web server** | Allow the Frappe Cloud network, ping, and SSH, HTTP, and HTTPS from the internet, and all outgoing connections. |
| **SSH only** | Allow the Frappe Cloud network, ping, and SSH from the internet, and all outgoing connections. |
| **Private only** | Allow the Frappe Cloud network and ping. Block other incoming connections. Allow all outgoing connections. |

If the server uses rulesets, the console removes them first.

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
