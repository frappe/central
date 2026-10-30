# Products

## Purpose

A Product is an app that customers can sign up for from its own page, such as Raven. The page links to `/dashboard/signup?product=<product key>`. Central shows the product's branding on every signup page and starts the trial on an image that has the app installed. A signup without `?product=` is a plain trial and does not change.

The Signups module holds Product, so it can move into its own app later.

## Configuration

System Managers and Product Operators create and edit products in Desk. Only a System Manager deletes one. See [Access](#access).

| Field | Rule |
|---|---|
| Product Key | Lowercase letters, numbers and hyphens. It is the record name and cannot change after creation. |
| Title | The product name. The signup pages use it as the logo's alternative text. |
| Enabled | A disabled product refuses new signups. Its existing sites keep running. |
| Logo | Shown with rounded corners next to the heading on the signup, login, verification, site name and setup pages. |
| Subtitle | Optional. Shown under the heading on the signup and login pages. |
| Setup Messages | Optional. One line each, such as `Setting up channels…`. The waiting page shows them one at a time, in a loop, while the product starts. Without them, the page shows general lines. |
| Signup App | The app module name, such as `raven`. Cargo tags the image that has this app installed with `app=<signup app>`. |
| Frappe Version | The Frappe branch of the trial image, `develop`, `version-<number>` or `version-<number>-hotfix`, such as `version-16-hotfix`. The default is `develop`. Cargo tags each image with the branch it was built on as `frappe_version=<branch>`. |
| Landing Route | Optional. Where the owner lands after signing in to a trial site, such as `/raven`, so the app runs its own setup. Empty opens Desk, which shows Frappe's setup wizard. |
| Trial Days | Days a trial site of this product runs from when Central records its site. 0 uses Central Settings, Trial Days. See [Trials](../../SPEC.md#trials). |
| Trial Deletion Days | Days a stopped trial site is kept before its server is terminated. 0 uses Central Settings, Trial Deletion Days. |
| Use Product Branding in Emails | Off uses Frappe Cloud's logo and name in emails. On uses the product's Logo and Title. See [Emails](#emails). |
| Email Notes | One extra paragraph for each lifecycle email about a site of this product. See [Emails](#emails). |
| Plan Notes | A short tag for each plan, which the site's plan list shows on a site of this product. See [Plans](#plans). |

Example: Product Key `raven`, Title `Raven`, Signup App `raven`, Frappe Version `version-16`. The signup link is `/dashboard/signup?product=raven`.

## Operation

`GET central.api.signups.get_product(product)` returns the title, logo, subtitle and setup messages of an enabled product, or nothing. Guests can call it, limited to 60 calls per minute for each IP address.

The console keeps `?product=` through signup, sign-in, email verification and the onboarding pages. The site name page sends it to `central.api.sites.create_trial_site(subdomain, request_key, product, team)`. The product is required, because only a product signup gets a free trial. Central refuses an unknown or disabled product before it asks the region for an image. See [Trial sites](../../../infrastructure/doctype/site/SPEC.md#configuration) for how the image is chosen.

A person who can edit a saved product has these Desk actions:

| Action | Effect |
|---|---|
| **Open Signup Page** | Opens `/dashboard/signup?product=<product key>`. It shows only on an enabled product. |
| **Preview Trial Images** | Lists the trial images of a region that have the signup app installed on the product's Frappe version, with the app version. Use it to check that Cargo built an image before you share the signup link. Only a System Manager sees it. |
| **Emails > Preview Email** | Shows the signup code email or a lifecycle email as a customer of this product sees it, with sample dates. It uses the unsaved changes on the form, so you can check a note before you save. |
| **Emails > Send Test Email** | Sends the same email to your own address, with "[Test]" in the subject. |
| **View > Sites**, **View > Trial Sites Report** | Open the product's sites and the trial report. Only a System Manager sees them. |

The **Signups** workspace in Desk links Product and the Trial Sites report.

The trial request saves a `site` part in the Resource Action payload with the product. The Site copies the product when the region creates it. See [Trial sites](../../../infrastructure/doctype/site/SPEC.md#what-the-record-holds).

A returning customer can start another product on the selected Team. Product signup links remain accessible after the customer has claimed a site. Onboarding reads only the selected product's site or creation. A claimed site opens the existing resource list with its address in the search field. An unfinished creation resumes its wait. A terminated site does not prevent a new signup. The browser stores a separate request key for each user, Team, and product.

Another product signup reuses the Team's billing profile and credit balance. It grants no additional welcome credit and does not extend its expiry.

An accepted invitation lets the member use the selected Team's balance when their role permits site creation. It grants no additional welcome credits. Membership does not consume the member's welcome-credit eligibility as an owner. If the member creates their own first Team, that Team can receive the [welcome credit](../../SPEC.md#welcome-credit).

A Product needs a Cargo image of type Apps for its signup app, on its Frappe version, in the region. Without one, the signup stops with "No trial image is available right now."

To move a product to another Frappe version:

1. Add the branch to Cargo Settings, Frappe Branches, and add the app to Signup Apps. Cargo then builds an Apps image of the app's newest stable release that runs on that branch.
2. On the Product, use **Preview Trial Images** for each trial region, after you set Frappe Version and save. Central cannot read the branches that Cargo builds, so this is the only check.
3. Revert Frappe Version if a region shows no image.

New trials use the new version. Existing sites stay on the version they started on. The app version is not set on the Product. Cargo builds only the newest stable release for each branch and retires older images, so a pinned version would soon have no image.

A customer can add another product's app to an open trial site. Pilot installs the release of that app that runs on the site's Frappe version, which can differ from the other product's Frappe Version.

## Access

A System Manager gives a Frappe team member the **Product Operator** role. The role covers every product. The person must be a System User to open Desk.

| Role | Product | Other DocTypes |
|---|---|---|
| System Manager | Create, read, edit, delete every product | Everything |
| Product Operator | Create, read and edit every product, and use Open Signup Page, Preview Email and Send Test Email | Files, to upload the logo. The Signups workspace shows them Product only. |

A Product Operator does not get Region, Image Offering, Site, Team or billing records, the Trial Sites report, or Preview Trial Images. Each of them reaches across every team, and only a System Manager may do that. To check an image, a Product Operator asks a System Manager. Those records belong to customer teams, and only a System Manager reads them across teams.

## Emails

Central sends the signup code and the [trial lifecycle emails](../../SPEC.md#operation). A product changes them in three ways.

**Branding.** With **Use Product Branding in Emails** on, the email header shows the product's Logo and Title instead of Frappe Cloud's. The code email also names the product, such as "123456 is your Raven signup code". The lifecycle emails of the product's sites use the same header. The logo must be a public file, because an email client loads it without a session. The footer still says that the person is a member of a Frappe Cloud team.

**Getting started.** With a **Getting Started URL**, the `site_ready` and `trial_unopened` emails show a **Get started** button that opens the site, and a **View docs** button to that page. Use the product's own guide or docs page, so the product team can change it without a change in Central. The address must start with `https://`. The `site_ready` subject also names the product, such as "Your Raven site is ready".

**Action links.** Email actions use the destinations below. Email previews use a sample site URL. In-app actions use the console routes.

| Email | Action destination |
|---|---|
| `site_ready`, `trial_unopened` | The created site's public URL and the product's Landing Route. A plain signup opens the site's root URL. |
| `trial_expiring`, `trial_ended`, `trial_deletion_soon` | The server's Upgrade dialog (`/servers/<server>?action=resize`). |
| `trial_converted` | Frappe Cloud's billing page. |
| `trial_deleted` | No action link. |

**Email Notes.** Each row adds text under the standard text of one email, only for sites of this product. Separate paragraphs with a blank line. Use it for product advice, such as what to do first. Central keeps the standard text, the dates and the button, so a note cannot change the trial terms.

| Email | Example note for Raven |
|---|---|
| `site_ready` | Create a channel and invite your team. |
| `trial_unopened` | Raven gives your team channels, threads and direct messages. |
| `trial_expiring` | Your channels and message history stay when you add a payment method. |
| `trial_converted` | Get the Raven mobile app from the App Store or Google Play. |
| `trial_deletion_soon` | Export a channel from its menu before the site is deleted. |
| `trial_ended` | Add a payment method to start your Raven site again. |

A note is plain text. Central escapes it, so HTML shows as text. Add at most one note for each email. Central also escapes the product title and every other value in an email, because a Product Operator or a Pilot writes them.

## Plans

A plan keeps one title and one price everywhere: in the site's plan list, on the Cloud dashboard and on the invoice. A product cannot rename a plan. It can add a **Plan Note** that tells its users who the plan suits. The site's plan list shows it as a tag next to the plan title, so keep it to a few words.

Each row names a Plan and a few words of plain text. Add at most one note for each plan. The site's plan list, `billing_api.get_plan_options`, returns each plan with a `note`: the note of the server's product for that plan, or `null`. The server's product is the product of its sites. A server with no product site, or with sites of more than one product, gets no notes.

| Plan | Example note for Raven |
|---|---|
| Standard | Up to 50 users |
| Pro | Up to 200 users |

A plan without a note still shows in the list, with its title and specs.

## Signup funnel

Central sends one Pulse event at each signup step with `frappe.utils.telemetry.capture`. A trial event goes through `central.signups.funnel.capture_trial_event`. It names the customer's Team, so events of one team can be joined, and it is queued only after the step commits, so a step that rolls back sends nothing. Each event goes to a Redis queue and is sent to Pulse later, so it adds no network call to the step. Events are sent only when Central has a Pulse key and telemetry is on. Pulse stores the user as a salted hash, so use Central records, not Pulse, to look up one customer.

| Event | Sent when | Properties |
|---|---|---|
| `signup_code_sent` | A new email asks for a code | `product` |
| `signup_verified` | A new email verifies its code and gets an account | `product` |
| `trial_requested` | Central saves a new trial request. A repeated request with the same key sends nothing. | `product`, `region`, and the Team's [signup attribution](#signup-attribution): `utm_source`, `utm_medium`, `utm_campaign`, `referrer`, `landing_product` |
| `trial_failed` | The trial's create Resource Action fails or times out | `product`, `status`, `error_code` |
| `trial_ready` | Central first records that the site answers. See [Readiness](../../../infrastructure/doctype/site/SPEC.md#readiness). | `product`, `seconds_to_ready` |
| `trial_claimed` | The customer first opens the site | `product` |
| `trial_converted` | A payment method converts the trial | `product`, `days_in_trial` |
| `trial_ended` | The trial reaches its end date without a payment method | `product` |
| `trial_deleted` | The ended trial's server is terminated | `product` |

A product app sends its own activation events from the trial site. Central puts `fc_team` in the site config of every Pilot server, so those events name the same Team and join this funnel. See [Integrations](../../../../spec/INTEGRATIONS.md).

A signed-in `verify_code` answer also carries the new session's CSRF token. In a product signup, the console then goes on to the site name page without a page load.

`signup_code_sent` and `signup_verified` happen before the customer has a Team, so Pulse files them under Central's own team. `send_code` and `verify_code` take an optional `product` only to label these events. An unknown product is dropped.

When a new email asks for a code, Central also looks up the request's country in a background job, so the team created after verification reads its billing country from the cache instead of waiting on the lookup.

## Signup attribution

A team created at signup keeps how its owner first found Frappe Cloud. The browser remembers the first public page a guest opens: `utm_source`, `utm_medium`, `utm_campaign` and `product` from its address, and the referring page when it is another site. It sends them with `central.api.sites.create_trial_team`. Central writes them in the same insert as the team, in the collapsed **Signup Attribution** section of Team. Nothing changes them later.

| Team field | Source |
|---|---|
| UTM Source, UTM Medium, UTM Campaign | The first page's query, trimmed to 140 characters |
| Landing Product | The first page's `product`, when that product exists |
| Referrer | The page that linked to the first page, trimmed to 1,000 characters |

A bad or unknown value is dropped and the team is still created. Join these fields with invoices to measure revenue by campaign. `trial_requested` carries the same fields, so Pulse can split the trial funnel by campaign.
