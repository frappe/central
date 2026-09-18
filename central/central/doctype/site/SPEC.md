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
claim_site --> Site.apply_subdomain --> rename_site --> sign in at url
```

- `Site.ensure_for` runs on every report a region makes about a machine, because the address arrives on one of them and nothing says which. It writes once. A machine that already has a site, runs no Pilot, or has no address yet is left alone.
- The requested name rides on the `Resource Action`, because the site it will rename does not exist until the region answers.
- `Asset.claim_admin_hostname` points a machine's admin UI at the hostname its region routes. Every Pilot machine needs it, whether or not anyone opens that UI: the bench is baked answering to a name that resolves nowhere. TLS stays off, because the regional proxy terminates it in front. A machine that is running but not yet answering leaves the marker empty, so the next report tries again.
- `Site.apply_subdomain` sends the rename once and returns without waiting. Pilot renames on its own task and keeps the old hostname serving, so the customer signs in at `url` while their name comes up behind them. Central keeps no copy of the name the bench uses: a copy goes stale when a rename succeeds and wrong when one fails, so `Site.get_bench_site_name` asks Pilot instead.
- Terminating the machine terminates the site, with nothing to write: the site reads its state from the machine.

## Readiness

Nothing is provisioned during signup, so readiness is not a build finishing. `central.api.sites.get_site` reports `ready` only when the machine is `Running` and one request to `<url>/api/method/ping` answers. The console polls that and hands the customer over the moment it turns true.

`central.api.sites.onboarding_status` answers the same question for a team rather than a named site, because the funnel cannot name a site whose address follows from a machine the region has not built yet.

## Sign-in

Pilot knows the site by its own name alone, which Central asks for, and mints a session on that host, which resolves nowhere outside the machine. `Site.get_login_url` puts the session on `Site.url`, because the public name is Central's.

## Configuration

| Setting | Location | Example |
|---|---|---|
| Image site name | `Central Settings.image_site_name` | `site.local` |
| Proxy zone | `Atlas Instance.proxy_domain` | `par-2.fc.frappe.dev` |
| Signup image | `Image Offering.available_in` = `Signup` or `Both` | one offering, lowest title, `Signup` preferred |
| Trial plan | `Plan.available_on_trial` | the cheapest eligible plan in the first Active region |

The image site name must match the name Cargo baked, or Pilot does not recognise the site and no login can be minted.

Give the trial plan the shape the image was baked at. A region restores a warm image from memory only when the vCPU count, memory and disk all match, and a trial that misses the shape cold-boots instead. `BUILD_VCPUS`, `BUILD_MEMORY_MIB` and `BUILD_DISK_MIB` in Cargo's `image_builder/builder.py` hold that shape.
