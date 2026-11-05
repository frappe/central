---
title: How Frappe Cloud works
description: Frappe Cloud gives you a server of your own. Four systems create it, run it, and manage what is inside it.
---

# How Frappe Cloud works

Frappe Cloud gives your team servers. A server is a virtual machine that belongs to your team only. You choose what runs inside it.

## From containers to servers

The first version of Frappe Cloud ran your bench as a container. The container shared a server with the benches of other teams. You worked with bench groups, benches, shared servers, and dedicated servers, and each one had its own settings.

Frappe Cloud now gives you a server directly. There is one thing to create and one thing to pay for. Everything inside the server is yours.

<ArchitectureDiagram variant="generations" />

| | v1: containers | v2: servers |
| --- | --- | --- |
| What you get | A bench in a container | A virtual machine |
| Who else runs on it | Other teams' benches on the same server | No other team. The server is yours alone. |
| What you choose | Bench group, then a shared or dedicated server | A region, an image, and a plan |
| Shell access | Limited to your bench | Root access over SSH |
| What runs inside | Frappe benches only | Frappe with Pilot, or plain Ubuntu |

## The four systems

Four systems work together. You use only the console. The other three work for you in the background.

<ArchitectureDiagram variant="stack" />

| System | What it does | What this means for you |
| --- | --- | --- |
| **Central** | Teams, members, roles, sign-in, billing, and the console | One account and one bill for all your servers |
| **Atlas** | Runs the servers in each region: hosts, disks, images, addresses, and web traffic | Your server, its snapshots, and its addresses in the region you choose |
| **Cargo** | Builds the server images and runs regional storage | A Frappe server starts with Pilot and a bench already installed |
| **Pilot** | Manages benches, sites, and apps inside one Frappe server | A web interface for your sites, backups, and domains |

### Central

Central is the console at the top of every request. It knows your team, your members, and their [roles](/team/roles). It checks each request before a region acts on it. It also signs you in to Pilot, so you do not need a second password.

### Atlas

Atlas is the system that runs servers in a region. Every region is its own Atlas, and one Atlas manages one region. It places your server on a physical host, gives it a disk and network addresses, and boots it from the image you choose. Each server is a [Firecracker](https://firecracker-microvm.github.io/) virtual machine. Read [Regions](/servers/regions) for everything an Atlas does for your servers.

Atlas also carries traffic to your server:

- A regional proxy receives web requests for `*.bom.frappe.cloud` names and for your own domains, and sends each one to the right server.
- A private network connects your servers in the same region over IPv6. A server keeps its addresses when Atlas moves it to another host.
- Atlas takes and keeps [snapshots](/servers/snapshots) of your server's disk.

### Cargo

Cargo builds the **Frappe** images. It installs Ubuntu, Pilot, and a bench on a build machine, then saves it as an image that Atlas can boot. This is why a new Frappe server is ready in minutes. Cargo also runs the object storage in each region. Read [Images](/servers/images) for each step of a build.

### Pilot

Pilot is the bench manager that runs inside a Frappe server. It manages three levels:

- A **bench** holds the app code and runs the web and background processes.
- A **site** is one Frappe installation with its own database, files, and domain. A bench can run many sites.
- An **app** is code that you install on a site, such as ERPNext.

Benches on the same server share it. To keep two workloads apart, put them on different servers. Read [What Pilot is](/pilot/).

## What runs inside a server

You choose an image when you [create a server](/servers/create).

| Image | Starts with | Use it for |
| --- | --- | --- |
| **Frappe** | Ubuntu 24.04 with [Pilot](/pilot/), a bench, and optionally a site | Frappe apps such as ERPNext, Helpdesk, and Raven |
| **Ubuntu** | A clean Ubuntu installation | Any other workload, such as a database, a CI runner, or your own service |

You can create many sites inside one Frappe server. When you need more room, or want to keep a workload apart, add another server. Read [Images](/servers/images) to see how each image is built.

## Regions and addresses

Each server runs in one [region](/servers/regions). A region is named with the code of its nearest airport. Mumbai is <Airport code="bom" />.

The region code is part of every address. In `erp.bom.frappe.cloud`, `erp` is the name you choose and `bom` is the region. The regional proxy serves these addresses over HTTPS, so you do not need a certificate for them.

You can also point your own domain, such as `erp.contrail.example`, to a site. Pilot gets a certificate for it on your server. Read [Domains and SSL](/pilot/domains).

## Your team and your bill

Each member sees only the servers of the teams they belong to. Each [role](/team/roles) decides what a member can do.

Each server has a plan with a monthly price. Your team gets [one invoice](/billing/) a month for all its servers and services.

## Learn more about each system

These projects are open source. Their documentation is written for developers and operators.

<Cards>
<Card title="Atlas handbook" link="https://frappe.github.io/atlas/" icon="lucide-globe">How regions run virtual machines, networks, and the web proxy.</Card>
<Card title="Pilot on GitHub" link="https://github.com/frappe/pilot" icon="lucide-plane">The bench manager, its commands, and its Admin UI.</Card>
<Card title="Cargo on GitHub" link="https://github.com/frappe/cargo" icon="lucide-package">Image builds and regional object storage.</Card>
</Cards>

## See also

- [Quick start](/get-started/quick-start)
- [Servers](/servers/)
- [What Pilot is](/pilot/)
- [Roles and permissions](/team/roles)
