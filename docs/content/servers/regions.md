---
title: Regions
description: Where your servers run, and how region codes appear in addresses.
---

# Regions

A region is a data center location where Frappe Cloud runs servers. Each server runs in one region. You select the region when you [create a server](/servers/create), and you cannot move a server to another region.

## Each region is an Atlas

Every region runs its own copy of Atlas, the system that runs servers. One Atlas manages one region with one provider. Regions do not share servers, disks, or networks.

The Atlas of a region does the work for each server in it:

| Job | What it means for your server |
| --- | --- |
| Places servers on hosts | Atlas selects a physical host with room for the size you choose. |
| Gives each server a disk | Atlas creates the disk from the [image](/servers/images) you select. |
| Runs each server | Each server is a separate virtual machine. Nothing else runs inside it. |
| Connects servers | Your servers in the region reach each other over a private IPv6 network. |
| Routes web traffic | A regional proxy sends requests for your sites and domains to the right server. |
| Keeps snapshots | Atlas takes and stores the [snapshots](/servers/snapshots) of your servers in the region. |
| Moves servers | Atlas can move a server to another host. The server keeps its addresses. |

Atlas saves each request before it acts, and checks the result after. If a step fails, it continues from the saved state instead of starting again. Read the [Atlas handbook](https://frappe.github.io/atlas/) for the details.

## Available regions

| Region | Code | Provider |
| --- | --- | --- |
| Mumbai, India | <Airport code="bom" /> | Frappe |

The **New server** page lists the regions that accept new servers. You can select a region in the list or on the map.

## Region codes

Each region has a short code. The code is the IATA code of the nearest airport. For example, <Airport code="bom" /> is the code of Chhatrapati Shivaji Maharaj International Airport in Mumbai.

The addresses of sites and servers include the region code after the first label:

| Address | Example |
| --- | --- |
| Site | `erp.bom.frappe.cloud` |
| Pilot on a Frappe server | `admin-vm-00006.bom.frappe.cloud` |

## Resources in a region

These resources belong to one region:

- **Private addresses.** A server can reach your other servers in the same region at their private IPv6 addresses. See [Networking and firewall](/servers/networking).
- **Snapshots.** You can restore a snapshot only to a new server in the same region. See [Snapshots](/servers/snapshots).
- **Prices.** Plan, public IPv4, and snapshot prices are set for each region.

## If a region is not available

| Message | Meaning |
| --- | --- |
| **Unreachable** under the region name | The console cannot reach the region now. |
| **This region is at capacity** | The region cannot fit a new server now. Select another region, or try again later. |
| **No regions are accepting new servers right now** | Try again later, or contact support. |

## See also

- [Servers](/servers/)
- [Create a server](/servers/create)
- [Networking and firewall](/servers/networking)
