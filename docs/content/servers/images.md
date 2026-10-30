---
title: Images
description: What an image is, which images you can choose, and how Frappe Cloud builds them.
---

# Images

An image is the disk that a new server starts from. It decides what is installed on the server when it boots. You select an image when you [create a server](/servers/create).

## Choose an image

| Image | The server starts with | Use it for |
| --- | --- | --- |
| **Frappe** | Ubuntu 24.04, [Pilot](/pilot/), and a bench. Some builds also have a site. | Frappe apps such as ERPNext, Helpdesk, and Raven. |
| **Ubuntu** | A clean Ubuntu installation. | Anything else: a database, a CI runner, an API, or a tool your team uses. |

Each image has builds. A build is one version of the image, such as **Version 16** with the date it was built. The **New server** page selects the newest build for you. Select an older build only when you need that exact version.

You can also start a server from a [snapshot](/servers/snapshots) of an Ubuntu server. Under **Image**, click **Snapshot**.

## Frappe image builds

A Frappe build has one of three types. Each type starts from the one before it.

| Type | Adds | The server header shows |
| --- | --- | --- |
| Base | Ubuntu 24.04, Pilot, and one bench with the Frappe framework at a fixed version. | **Open Pilot** |
| Site | One site with no apps. | **Visit site** |
| Apps | An app and the apps it needs, installed on the site. | **Visit site** |

After the server starts, you manage it in Pilot. You can [create more sites](/pilot/sites) and [install more apps](/pilot/apps) on the same server.

## How a Frappe image is built

Cargo builds the Frappe images in each region. A build takes these steps:

1. Cargo starts a temporary build machine in the region.
2. It installs Pilot and creates the bench at the exact Frappe version of the build. Pilot downloads the built assets for that version instead of building them.
3. For a Site or Apps build, it creates the site and installs the apps.
4. It checks that the site answers requests.
5. It saves the disk as an image in the region, then deletes the build machine.

Atlas keeps the image and makes it available to every host in the region. This is why a new Frappe server is ready in minutes: it does not install anything at first boot.

## How an Ubuntu image is built

Atlas builds the Ubuntu images from Ubuntu releases. It adds the parts a server needs to start in the region, so the server reads its network settings and your [SSH keys](/servers/access) when it boots. Nothing else is installed.

## Images and regions

An image belongs to one region. A server starts only from an image in its own region. The **New server** page shows the builds of the region that you select.

## See also

- [Create a server](/servers/create)
- [How Frappe Cloud works](/get-started/how-it-works)
- [What Pilot is](/pilot/)
- [Snapshots](/servers/snapshots)
