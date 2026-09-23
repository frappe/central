# Trial sites

## Purpose

A `Site` record is the site a Pilot image already carries, on the machine that runs it. Central builds no site: [Cargo](../../../../../cargo/docs/image.md) bakes one bench and one site into every image, and the image answers for it on a `site-*` hostname alias. Starting a trial therefore starts a machine, and nothing else.

That is why a trial is one record and not two. A trial customer buys a site, the site is the machine, and the console shows one row for the pair.

## What the record holds

Only what belongs to the site. Its address is its name and its state is the machine's, so neither is stored where the two could drift apart.

| Field | Meaning |
|---|---|
| `site_name` | the public address, which is also the record's name |
| `team` | the owning team |
| `server` | the Virtual Machine the site runs on |
| `ready_at` | the first successful public readiness probe |
| `claimed_at` | the first successful login handoff |
| `rename_task` | the Pilot task that accepted the requested rename |
| `rename_error` | a safe reason when Pilot did not accept the rename |
| `rename_error_log` | the related operator Error Log |

`Site.url` is `https://` and the name. `Site.status` reads the machine's status. Neither is a column.

## The address

The regional proxy decodes a VM's mesh address from the hostname label, so Central builds both of a machine's public names itself, with no call to the region.

| Name | Pattern | Answers with |
|---|---|---|
| Bench admin | `admin-vm-<label>.<proxy domain>` | the bench admin UI |
| Site | `site-<label>.<proxy domain>` | the baked site |

`Region.get_vm_site_host` builds the second one. `<label>` is the base-36 encoding of the mesh address, and `<proxy domain>` is `Region.proxy_domain`.

## Operation

```text
create_trial_site(subdomain) --> queued Resource Action holds the name --> warm image restores
                                                                         |
observe_server --> VirtualMachine.claim_admin_hostname     (every Pilot machine, once)
               --> Site.ensure_for                (carries the requested name)
                                                                         |
onboarding_status --> GET <url>/api/method/ping --> ready
                                                                         |
claim_site --> mint login for site.local --> sign in at url
                                      |
                                      +--> enqueue rename_site

get_site --> read readiness only
login_site --> mint a fresh login for site.local
```

- `Site.ensure_for` runs on every report a region makes about a machine, because the address arrives on one of them and nothing says which. It writes once. A machine that already has a site, runs no Pilot, or has no address yet is left alone.
- The requested name rides on the `Resource Action`, because the site it will rename does not exist until the region answers.
- `VirtualMachine.claim_admin_hostname` tells Pilot to replace its local `admin.local` name with the `admin-vm-*` hostname that the regional proxy already routes. Central does not create or change a proxy route. TLS stays off because the regional proxy terminates it. A machine that is not running, a failed request, or a response without a task ID leaves the marker empty, so the next report tries again.
- A successful claim records `claimed_at`, returns the login URL, and enqueues the rename after the database commit. The response does not wait for Pilot to accept or finish the rename.
- `Site.apply_subdomain` creates one Pilot rename task. Pilot keeps the automatic hostname serving while the requested hostname comes up.
- A rename failure stays on the Site with a safe reason and an Error Log link. A System Manager can use **Retry Site Rename** until Pilot accepts a task.
- Terminating the machine terminates the site, with nothing to write: the site reads its state from the machine.

## Readiness

Nothing is provisioned during signup, so readiness is not a build finishing. `central.api.sites.get_site` reports `ready` when one request to `<url>/api/method/ping` answers. The first successful probe records `ready_at` and queues one `site_ready` notification after commit. It does not create a login session. The console polls this read and calls the POST-only `central.api.sites.login_site` operation when the user opens the site.

`central.api.sites.onboarding_status` follows the latest Site creation requested by the current user. It does not adopt a normal server creation or another team member's request. A Running state report schedules a full server refresh, so the Site record does not wait for the periodic reconciliation job.

## Sign-in

Every signup image contains `site.local`. Central mints the session for that stable image name and puts the returned session on `Site.url`, because the public name is Central's. A Pilot 401 leaves the site unclaimed and tells the console to retry with bounded backoff for up to 120 seconds. Other login failures return no URL and use the manual sign-in fallback. Central waits up to 120 seconds for each login request.

## Configuration

| Setting | Location | Example |
|---|---|---|
| Image site name | Cargo image invariant | `site.local` |
| Proxy zone | `Region.proxy_domain` | `par-2.fc.frappe.dev` |
| Signup image | `Image Offering.available_in` = `Signup` or `Both` | one offering, lowest title, `Signup` preferred |
| Signup image tags | `SIGNUP_IMAGE_TAGS` in `central/site_provisioning.py` | `has_site=1`, `frappe_version=develop` |
| Trial plan | `Plan.available_on_trial` | the cheapest eligible plan in the first Active region |

Cargo must bake the image site as `site.local`, or Pilot does not recognise the site and no login can be minted.

Central asks the region for the offering tags and the signup tags together, and takes the newest image that comes back. Change `SIGNUP_IMAGE_TAGS` to move signups to another Frappe version. The region matches a tag exactly, so an image without the tag never qualifies.

Give the trial plan the shape the image was baked at. A region restores a warm image from memory only when the vCPU count, memory and disk all match, and a trial that misses the shape cold-boots instead. `BUILD_VCPUS`, `BUILD_MEMORY_MIB` and `BUILD_DISK_MIB` in Cargo's `image_builder/builder.py` hold that shape.
