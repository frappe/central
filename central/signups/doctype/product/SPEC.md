# Products

## Purpose

A Product is an app that customers can sign up for from its own page, such as Raven. The page links to `/dashboard/signup?product=<product key>`. Central shows the product's branding on every signup page and starts the trial on an image that has the app installed. A signup without `?product=` is a plain trial and does not change.

The Signups module holds Product, so it can move into its own app later.

## Configuration

System Managers create and edit products in Desk. Nobody else can read the DocType.

| Field | Rule |
|---|---|
| Product Key | Lowercase letters, numbers and hyphens. It is the record name and cannot change after creation. |
| Title | The product name. The signup pages use it as the logo's alternative text. |
| Enabled | A disabled product refuses new signups. Its existing sites keep running. |
| Logo | Shown next to the heading on the signup, login, verification, site name and setup pages. |
| Subtitle | Optional. Shown under the heading on the signup and login pages. |
| Signup App | The app module name, such as `raven`. Cargo tags the image that has this app installed with `app=<signup app>`. |
| Landing Route | Optional. Where the owner lands after signing in to a trial site, such as `/raven`, so the app runs its own setup. Empty opens Desk, which shows Frappe's setup wizard. |

Example: Product Key `raven`, Title `Raven`, Signup App `raven`. The signup link is `/dashboard/signup?product=raven`.

## Operation

`GET central.api.signups.get_product(product)` returns the title, logo and subtitle of an enabled product, or nothing. Guests can call it, limited to 60 calls per minute for each IP address.

The console keeps `?product=` through signup, sign-in, email verification and the onboarding pages. The site name page sends it to `central.api.sites.create_trial_site(subdomain, request_key, team, product)`. Central refuses an unknown or disabled product before it asks the region for an image. See [Trial sites](../../../infrastructure/doctype/site/SPEC.md#configuration) for how the image is chosen.

Operators have two Desk actions on a saved product:

- **Preview Trial Images** lists the region's trial images that have the signup app installed, with the app version. Use it to check that Cargo built an image before you share the signup link.
- **Open Signup Page** opens `/dashboard/signup?product=<product key>`. It shows only on an enabled product.

The trial request saves a `site` part in the Resource Action payload with the product. The Site copies the product when the region creates it. See [Trial sites](../../../infrastructure/doctype/site/SPEC.md#what-the-record-holds).

A returning customer can start another product on the selected Team. Product signup links remain accessible after the customer has claimed a site. Onboarding reads only the selected product's site or creation. A claimed site opens the existing resource list with its address in the search field. An unfinished creation resumes its wait. A terminated site does not prevent a new signup. The browser stores a separate request key for each user, Team, and product.

Another product signup reuses the Team's billing profile and credit balance. It grants no additional welcome credits and does not extend their expiry.

An accepted invitation lets the member use the selected Team's balance when their role permits site creation. It grants no additional welcome credits. Membership does not consume the member's welcome-credit eligibility as an owner. If the member creates their own first Team, that Team can receive the configured welcome credits.

A Product needs a Cargo image of type Apps for its signup app in the region. Without one, the signup stops with "No trial image is available right now."

## Signup funnel

Central sends one Pulse event at each signup step with `frappe.utils.telemetry.capture`. Each event goes to a Redis queue in the request and is sent to Pulse later, so it adds no network call to the step. Events are sent only when Central has a Pulse key and telemetry is on. Pulse stores the user as a salted hash, so use Central records, not Pulse, to look up one customer.

| Event | Sent when | Properties |
|---|---|---|
| `signup_code_sent` | A new email asks for a code | `product` |
| `signup_verified` | A new email verifies its code and gets an account | `product` |
| `trial_requested` | Central saves a new trial request. A repeated request with the same key sends nothing. | `product`, `region` |
| `trial_failed` | The trial's create Resource Action fails or times out | `product`, `status`, `error_code` |
| `trial_ready` | The site first answers its readiness probe | `product`, `seconds_to_ready` |
| `trial_claimed` | The customer first opens the site | `product` |

`send_code` and `verify_code` take an optional `product` only to label these events. An unknown product is dropped.

When a new email asks for a code, Central also looks up the request's country in a background job, so the team created after verification reads its billing country from the cache instead of waiting on the lookup.

## Signup attribution

A team created at signup keeps how its owner first found Frappe Cloud. The browser remembers the first public page a guest opens: `utm_source`, `utm_medium`, `utm_campaign` and `product` from its address, and the referring page when it is another site. It sends them with `central.api.sites.create_trial_team`. Central writes them in the same insert as the team, in the collapsed **Signup Attribution** section of Team. Nothing changes them later.

| Team field | Source |
|---|---|
| UTM Source, UTM Medium, UTM Campaign | The first page's query, trimmed to 140 characters |
| Landing Product | The first page's `product`, when that product exists |
| Referrer | The page that linked to the first page, trimmed to 1,000 characters |

A bad or unknown value is dropped and the team is still created. Join these fields with invoices to measure revenue by campaign. Pulse holds the funnel counts.
