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
| `asset` | the machine the site is |
| `claimed_at` | the first successful login handoff |

`Site.url` is `https://` and the name. `Site.status` reads the machine's status. Neither is a column.

## The address

The regional proxy decodes a VM's mesh address from the hostname label, so Central builds both of a machine's public names itself, with no call to the region.

| Name | Pattern | Answers with |
|---|---|---|
| Bench admin | `admin-vm-<label>.<proxy domain>` | the bench admin UI |
| Site | `site-<label>.<proxy domain>` | the baked site |

`Atlas Instance.get_vm_site_host` builds the second one. `<label>` is the base-36 encoding of the mesh address, and `<proxy domain>` is `Atlas Instance.proxy_domain`.

## Operation

```text
create_trial_site(subdomain) --> Resource Action holds the name --> warm image restores
                                                                         |
observe_server --> Asset.claim_admin_hostname     (every Pilot machine, once)
               --> Site.ensure_for                (carries the requested name)
                                                                         |
onboarding_status --> GET <url>/api/method/ping --> ready
                                                                         |
claim_site --> mint login for site.local --> sign in at url
                                      |
                                      +--> enqueue rename_site
```

- `Site.ensure_for` runs on every report a region makes about a machine, because the address arrives on one of them and nothing says which. It writes once. A machine that already has a site, runs no Pilot, or has no address yet is left alone.
- The requested name rides on the `Resource Action`, because the site it will rename does not exist until the region answers.
- `Asset.claim_admin_hostname` points a machine's admin UI at the hostname its region routes. Every Pilot machine needs it, whether or not anyone opens that UI: the bench is baked answering to a name that resolves nowhere. TLS stays off, because the regional proxy terminates it in front. A machine that is running but not yet answering leaves the marker empty, so the next report tries again.
- A successful claim records `claimed_at`, returns the login URL, and enqueues the rename after the database commit. The response does not wait for Pilot to accept or finish the rename.
- `Site.apply_subdomain` creates one Pilot rename task. Pilot keeps the automatic hostname serving while the requested hostname comes up.
- Terminating the machine terminates the site, with nothing to write: the site reads its state from the machine.

## Readiness

Nothing is provisioned during signup, so readiness is not a build finishing. `central.api.sites.get_site` reports `ready` only when the machine is `Running` and one request to `<url>/api/method/ping` answers. The console polls that and hands the customer over the moment it turns true.

`central.api.sites.onboarding_status` follows the latest Site creation requested by the current user. It does not adopt a normal server creation or another team member's request. A Running state report schedules a full server refresh, so the Site record does not wait for the periodic reconciliation job.

## Sign-in

Every signup image contains `site.local`. Central mints the session for that stable image name and puts the returned session on `Site.url`, because the public name is Central's. A Pilot 401 leaves the site unclaimed and tells the console to retry with bounded backoff for up to 120 seconds. Other login failures return no URL and use the manual sign-in fallback. Central waits up to 120 seconds for each login request.

## Configuration

| Setting | Location | Example |
|---|---|---|
| Image site name | Cargo image invariant | `site.local` |
| Proxy zone | `Atlas Instance.proxy_domain` | `par-2.fc.frappe.dev` |
| Signup image | `Image Offering.available_in` = `Signup` or `Both` | one offering, lowest title, `Signup` preferred |
| Trial plan | `Plan.available_on_trial` | the cheapest eligible plan in the first Active region |

Cargo must bake the image site as `site.local`, or Pilot does not recognise the site and no login can be minted.

Give the trial plan the shape the image was baked at. A region restores a warm image from memory only when the vCPU count, memory and disk all match, and a trial that misses the shape cold-boots instead. `BUILD_VCPUS`, `BUILD_MEMORY_MIB` and `BUILD_DISK_MIB` in Cargo's `image_builder/builder.py` hold that shape.
