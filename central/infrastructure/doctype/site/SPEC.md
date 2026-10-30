# Trial sites

## Purpose

Customer names obey the scoped [blocked domains](../blocked_domain/SPEC.md). Central checks signup availability, queued creation requests, Site saves, and Site renames on the server.

A `Site` record is the site a Pilot image already carries, on the machine that runs it. Central builds no site: [Cargo](../../../../../cargo/docs/image.md) bakes one bench into every Pilot image, and one site into an image tagged `has_site=1`. That image answers for the site on a `site-*` hostname alias. A bench-only image, tagged `has_site=0`, has no site and gets no `Site` record. Starting a trial therefore starts a machine, and nothing else.

That is why a trial is one record and not two. A trial customer buys a site, the site is the machine, and the console shows one row for the pair.

## What the record holds

Only what belongs to the site. Its address is its name and its state is the machine's, so neither is stored where the two could drift apart.

| Field | Meaning |
|---|---|
| `site_name` | the public address, which is also the record's name |
| `team` | the owning team |
| `server` | the Virtual Machine the site runs on |
| `subdomain` | the name the customer chose, copied from the create Resource Action; the rename target |
| `product` | the [Product](../../../signups/doctype/product/SPEC.md) the trial request named, copied from the create Resource Action; empty for a plain trial |
| `ready_at` | the first successful public readiness probe |
| `claimed_at` | the first successful login handoff |
| `rename_task` | the Pilot task that accepted the requested rename |
| `rename_status` | the latest observed physical rename task status |
| `rename_completed_at` | when Central confirmed physical rename success |
| `renamed_at` | when a sign-in first found the requested hostname answering |
| `rename_error` | a safe reason when Pilot did not accept or complete the rename |
| `rename_diagnostic` | the operator traceback of the latest rename failure, readable only by a System Manager |

`Site.url` is `https://` and the name. `Site.primary_url` is the requested hostname after `renamed_at` is set, otherwise `Site.url`. `Site.status` reads the machine's status. None of these is a column.

## The address

The regional proxy decodes a VM's mesh address from the hostname label, so Central builds both of a machine's public names itself, with no call to the region.

| Name | Pattern | Answers with |
|---|---|---|
| Bench admin | `admin-vm-<label>.<proxy domain>` | the bench admin UI |
| Site | `site-<label>.<proxy domain>` | the baked site |

`Region.get_vm_site_host` builds the second one. `<label>` is the base-36 encoding of the mesh address, and `<proxy domain>` is `Region.proxy_domain`.

## Operation

The funnel first calls `central.api.sites.create_trial_team`. A user with no team gets one named after them. A user with a team keeps it.

```text
create_trial_site(subdomain) --> queued Resource Action holds the name --> warm image restores
                                                                         |
observe_server --> Site record --> queue VirtualMachine.claim_admin_hostname after commit
               --> Site.create_once_addressable   (site images only; carries the requested name)
               --> Site.route_subdomain           (queued; routes the requested name to the server)
                                                                         |
onboarding_status --> GET <url>/api/method/ping --> ready
                                                                         |
claim_site --> mint login for site.local --> sign in at the requested name, or at url until it answers
                                      |
                                      +--> enqueue physical site rename

get_site --> read readiness only
login_site --> mint a fresh login for site.local
```

- `Site.create_once_addressable` runs on every report a region makes about a machine, because the address arrives on one of them and nothing says which. It writes once, and it copies the requested name to `Site.subdomain`. A machine that already has a site, has `has_site` off, runs no Pilot, or has no address yet is left alone.
- `Virtual Machine.has_site` records whether the machine's image carries a site. `VirtualMachine.create_from_action` sets it from the image's `has_site` tag. The machine owns this fact. The Resource Action is only the request.
- The requested name rides on the `Resource Action`, because the site it will rename does not exist until the region answers.
- A new Site with a requested name queues `Site.route_subdomain`. It creates the [Site Domain](../site_domain/SPEC.md) of the requested name for the server, unless the name has a route already. The Pilot image serves its site on every name in its zone, so the requested name answers as soon as the route is Active, before the rename. A job keeps a refused route from stopping the Site record. The rename later registers the same route again, which is safe.
- `VirtualMachine.claim_admin_hostname` tells Pilot to replace its local `admin.local` name with the `admin-vm-*` hostname that the regional proxy already routes. Observation queues it after commit, after the Site record is available. A slow Admin request does not delay site discovery. TLS stays off because the regional proxy terminates it. A failed request or a response without a task ID leaves the marker empty, so the next report queues another attempt.
- A successful claim records `claimed_at`, returns the login URL, and enqueues the rename after the database commit. The response does not wait for Pilot to accept or finish the rename.
- `Site.apply_subdomain` submits a Pilot rename from `site.local` to the requested hostname with `make_primary=True`. Pilot moves the directory, makes the requested hostname primary, and keeps the old hostname by default. The `rename_task` field stores the accepted task and `rename_status` starts at `queued`. Signup does not wait for submission or completion.
- Every five minutes, `poll_site_renames` checks pending renames on running servers. Each check has its own exception handler. A failed check leaves the status pending and does not stop the other checks. Central reads the bench task endpoint, which still works after the site directory moves. It stores Pilot's task status and records `rename_completed_at` only after `success`. Failed or killed tasks keep their failure details on the Site for an operator to inspect in Pilot. Existing sites with a recorded task and no tracking status are left unchanged.
- A rename failure stays on the Site with a safe reason and an operator diagnostic. A System Manager can use **Retry Site Rename** until Pilot accepts a task.
- Terminating the machine terminates the site, with nothing to write: the site reads its state from the machine.

## Readiness

Nothing is provisioned during signup, so readiness is not a build finishing. A site is ready when one request to `<url>/api/method/ping` answers. `central.api.sites.get_site` and `central.api.sites.onboarding_status` report `ready` but do not record it, because Frappe rolls back the writes of a GET request. These record readiness: the POST operations `claim_site` and `login_site`, the **Check Readiness** Desk action, and the scheduled job `central.infrastructure.doctype.site.site.record_ready_sites`. The job runs every 5 minutes and probes each Active trial site that has no `ready_at` and whose server is Running, so readiness does not wait for the customer to come back. A sleeping server is not Running, so the job does not wake it. The first recorded probe sets `ready_at`, queues one `site_ready` notification after commit, and sends the `trial_ready` [funnel event](../../../signups/doctype/product/SPEC.md#signup-funnel). A locking read makes sure that this happens once. A probe does not create a login session. The console polls `onboarding_status` and calls `claim_site` when the site is ready.

`central.api.sites.onboarding_status(team, product)` first finds the selected product's non-terminated Site that the caller can view in the Team. If none exists, it follows the latest matching Site creation requested by the caller. A plain signup follows only creations without a product. It does not adopt a normal server creation or another team member's pending request. The response reports whether the site was claimed, so a returning customer can find it in the resource list. A Running state report schedules a full server refresh, so the Site record does not wait for the periodic reconciliation job.

### Setup journey

`onboarding_status` also returns `journey`, which the waiting page shows. `central.signups.journey.SetupJourney` builds it from the records that own each step, so the page never moves ahead of Central.

| Field | Value |
| --- | --- |
| `phase` | The milestone the site works towards: `booking` while the creation is Queued or Dispatching, `server` until the server is Running, `app` until the site answers, then `signing`. `failed` when the creation fails or times out, or the server fails. |
| `subdomain`, `domain` | The name the customer chose and the zone of the region. |
| `region` | The region's display name, country code and map coordinates. |
| `started_at` | When the creation was requested. |
| `eta_seconds` | The median time from request to a site that answers, over the latest 50 trials in the region. It is null with fewer than 3 trials, and it is cached for 10 minutes. |
| `reference` | The creation's Resource Action name. The page shows it on a failure, so support can find the request. |

The page shows four milestones: Queued (until the region takes the request), Provisioning (until the server runs), Starting (until the site answers) and Arrived (the customer is signed in). The current milestone is highlighted, and a status line under them says what happens now. It shows `Delayed` after twice the estimate, and it leaves for the site about 1 second after the sign-in link arrives.

## Sign-in

Central signs in on the customer hostname as soon as it answers. Until then, sign-in uses the automatic `Site.url` and does not wait. A slow or failed route only delays the switch. Central tries `site.local` first, then the customer name after Pilot renames the directory. The first sign-in on the customer hostname sets `renamed_at`; this timestamp does not confirm completion of the physical rename. From then on, the console and the server registry show `Site.primary_url`, and readiness probes still use `Site.url`. Claiming schedules the physical rename after the response.

On a trial site, a member of the site's team signs in as their own user. Pilot creates the user as a System Manager the first time they open the site, so they can finish the app's own setup. An operator outside the team, and every other site, signs in as Administrator.

A Pilot 401 leaves the site unclaimed and tells the console to retry with bounded backoff for up to 120 seconds. Other login failures return no URL and use the manual sign-in fallback. Central waits up to 120 seconds for each login request.

## Plan change page

A site's users have no Central account. When a plan change from the site stops the server, Central shows them a public page that follows the change. The page lives on Central, so it stays up while the server restarts. The site's plan list, `billing_api.get_plan_options`, leaves out a plan whose disk is smaller than the server's disk, because a plan change takes the plan's own disk and a disk can't shrink. Each plan in it carries the [plan note](../../../signups/doctype/product/SPEC.md#plans) of the site's product.

1. `central.billing.api.billing_api.change_plan` queues the resize and returns `progress_url`. It returns a URL only when the server runs exactly one Site.
2. The URL is `/upgrading?action=<Resource Action>&site=<Site>&_signature=<signature>`. Frappe's `get_signed_params` signs it with the site secret. The link does not expire.
3. `central/www/upgrading.py` checks the signature and renders the page. A wrong signature, or an action that does not resize the Site's server, shows "This link is not valid".
4. The page asks `central.api.sites.plan_change_progress` every 3 seconds. The endpoint allows guests, checks the same signature, and allows 60 requests a minute for each action.
5. The step comes from the Resource Action status: `saving`, `moving`, `starting`, `ready` or `failed`. The step is `ready` only when `Site.routed_url` answers a ping. `Site.routed_url` is the chosen name when its Site Domain is `Active`, else `Site.primary_url`.
6. On `ready`, the page counts down 5 seconds and opens `Site.routed_url` on the product's Landing Route, such as `/raven`. The user can stay on the page.
7. The page names only what changes, such as "Memory goes from 1 GB to 2 GB". It shows a plan title below the size only when the title is not the size.

Every notification that refers to a Site, and every trial email, names the Site by the host of `Site.routed_url`. The "Get started" button opens the same host on the product's Landing Route.

`PlanChange` in `plan_change.py` owns the link and the progress. A developer bench also serves `/upgrading?preview=1`, which shows every step with sample data.

## Operator actions

The Resource Action of a site creation shows a **Site Setup** timeline with the time of each step: requested, sent to the region, server created, site addressable, site answered, signed in, and name applied. The first step with no time is where the signup stopped. A failed creation or a failed rename shows its error on that step.

A System Manager has two actions on the Site form in Desk:

| Action | Effect |
| --- | --- |
| **Open as Administrator** | Opens a one-click session on the site. Central records it as a Comment on the Site and on its server. |
| **Check Readiness** | Probes the site's address now, and records readiness when the site answers. |

## Migration

The `record_server_has_site` patch backfills `Virtual Machine.has_site` from the create request of each server. It sets `has_site` when the requested image tags have `has_site = 1` or the request was a trial.

The patch removes a Site only when the request of its server names an image with `has_site = 0`. It first clears the `site` link of each [Site Domain](../site_domain/SPEC.md) that points at that Site. When no request names the image, the Site record is the only evidence left. The patch then keeps the Site and sets `has_site = 1`.

## Configuration

| Setting | Location | Example |
|---|---|---|
| Image site name | Cargo image invariant | `site.local` |
| Proxy zone | `Region.proxy_domain` | `par-2.fc.frappe.dev` |
| Signup image | `Image Offering.available_in` = `Signup` or `Both` | one offering, lowest title, `Signup` preferred |
| Signup image tags | `SIGNUP_IMAGE_TAGS` in `central/site_provisioning.py` | Plain trials: `has_site=1`, `frappe_version=version-16-hotfix`. Product trials use the product's configured Frappe version. |
| Product app tag | [`Product.signup_app`](../../../signups/doctype/product/SPEC.md) | `app=raven` |
| Product Frappe version tag | [`Product.frappe_version`](../../../signups/doctype/product/SPEC.md) | `frappe_version=version-16` |
| Trial region and plan | `Plan.available_on_trial` | the first Active region, by name, that has a proxy zone, offers a trial plan, and has a trial image for the signup. Central takes that region's cheapest active plan marked Available on Trial that is eligible for the Team. This applies to production and staging Teams. No marked eligible plan means no trial is available. |

Cargo must bake the image site as `site.local`, or Pilot does not recognise the site and no login can be minted.

Central asks the region for the offering tags and the signup tags together, and takes the newest image that comes back. A region without a matching image is skipped, so the next region can serve the trial. The region matches a tag exactly, so an image without the tag never qualifies. A product signup also asks for `app=<signup app>`, and replaces `frappe_version` with the product's Frappe Version. Set Frappe Version on the Product to move one product to another Frappe version. `SIGNUP_IMAGE_TAGS` sets the version only when no product is named. A plain signup drops every image tagged `app`, because the region cannot filter on a missing tag.

The site name page shows the zone of that same region: `central.api.sites.site_domain(team, product)` makes the region choice that creation makes. `central.api.sites.check_subdomain` checks a name in every trial zone, because the region is chosen only when the site is created. A name is taken while a Site on a server that is not Terminated holds it, or while a Site Domain holds it. A terminated server's Site stays as history and does not hold the name. Its Site Domain holds the name until the route removal succeeds, because registration refuses a name that another server's route holds.

Give the trial plan the shape the image was baked at. A region restores a warm image from memory only when the vCPU count, memory and disk all match, and a trial that misses the shape cold-boots instead. `BUILD_SPEC` in Cargo's `cargo/image_builder/doctype/pilot_image/builder.py` holds that shape.
