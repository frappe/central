# Affiliates

## Purpose

An affiliate is a person who shares a link to Frappe Cloud or to a [Product](../product/SPEC.md). Central records the visits that the link brings and the teams that sign up from it, so a System Manager can see which affiliate brought which signup. Commission and payouts are not part of Central yet.

## Records

All three DocTypes are in the Signups module. Only a System Manager can read, create or change them. An affiliate never reads them directly.

| DocType | Name | One record is |
|---|---|---|
| Affiliate | `AFF-00001` | A person who applied to be an affiliate. |
| Affiliate Link | The slug, such as `bwh` | A named link an affiliate shares at `/r/<slug>`. It fixes the product, source and campaign of its visits. |
| Affiliate Visit | A random hash | A click on an affiliate link, for one product and one set of UTM values. The visitor's cookie holds this name. |
| Product Referral | `<team>::<product key>` | The affiliate credited with a team's signup for a product. |

### Affiliate

| Field | Rule |
|---|---|
| User | The applicant. One Affiliate for each user. It cannot change. |
| Status | Pending, Active, Rejected or Disabled. |
| Affiliate Code | The code in the link `/r/<code>`. Central sets it once, at the first approval. It cannot change after that. It is empty until then. |
| Requested On, Reviewed By, Reviewed On, Rejection Reason | The last request and the last review. Track Changes keeps the earlier values. |

### Affiliate Visit

A visit holds the affiliate, the named link (empty for the main code), the product, the `utm_source`, `utm_medium` and `utm_campaign` of the link, the visitor's country and Last Clicked On. An empty product is a link to Frappe Cloud itself. When a Product Referral for a product uses a visit with an empty product, the visit takes that product, so the click counts for the product the person chose. A background job looks up the country from the visitor's IP address after the click, so the redirect does not wait. Central keeps only the country name, never the IP address or an email.

### Product Referral

A referral holds the referred team, the product, the affiliate, the visit, and the UTM values copied from the visit. Its name is `<team>::<product key>`, for example `TEAM-00012::raven`. A signup to Frappe Cloud itself has an empty product and uses the key `fc`, for example `TEAM-00012::fc`. No Product can use the key `fc`.

The name is the unique key. The database refuses a second referral for the same team and product, so the first referral is final. A team can have one referral for each product and one for `fc`.

## Operation

### Apply

A signed-in user calls `POST central.api.affiliates.apply`. It needs no form fields. It is safe to repeat.

| Current status | Result |
|---|---|
| No Affiliate | Central creates one as Pending. |
| Pending or Active | Nothing changes. |
| Rejected | The same Affiliate becomes Pending again with a new Requested On. Central clears the review fields. |
| Disabled | Refused. Only a System Manager can enable the affiliate again. |

`GET central.api.affiliates.get_affiliate` returns the caller's own `status`, the `affiliate_code` when Active, and the `rejection_reason` when Rejected. It returns nothing when the caller never applied. Both calls return only the caller's own record.

### Console

Every signed-in user sees **Affiliate** in the console sidebar, at `/dashboard/affiliate`. The page shows one state:

| Status | Page |
|---|---|
| Never applied | **Become an affiliate**, which calls `apply`. |
| Pending | The request is under review. |
| Rejected | The reason, and **Request again**. |
| Disabled | The account is paused. There is no button. |
| Active | One page, top to bottom: five numbers (clicks, signups, paying customers, click to paid, and earnings per click), the link builder with Performance Overview (clicks, signups and paying customers per day) beside it, the conversion funnel, earnings by product and by campaign, Where your customers come from, the Campaigns and Breakdown charts side by side, and Retention. |

The Campaigns chart shows clicks, signups and paying customers for the top 8 links by signups, the main link `/r/<code>` included. The Breakdown chart shows the same numbers for each source or product, with a switch between Source and Product. Earnings by product is a table of each product's clicks, signups, paying customers, conversion rate (paying customers out of signups), earnings and earnings per click. Earnings by campaign is a ring chart of each campaign's share of the earnings, with the total in the middle. Both use the sample rate of 50 USD for each paying customer until commission is decided.

Where your customers come from colours the dots of each country on the server map, in four shades of blue. A darker shade means more signups and a higher conversion rate (paying customers out of signups) than the other countries. Hover shows the country's clicks, signups and conversion rate. Beside the map are the top 10 countries by signups. A country picker shows one country and zooms to it. **View all countries** opens a scrollable list of every country with clicks, signups, paying customers and conversion rate. An unknown country reads Unknown, and is listed but not drawn. The country dots come from `dashboard/src/lib/countryDots.ts`, which `dashboard/scripts/generate_country_dots.py` makes from the Natural Earth country borders.

Clicks, signups, paying customers and earnings per click show the change against the period of the same length just before, as a percent. Click to paid shows how many clicks it counts.

The link builder asks for a campaign, a product (from `get_link_products`, the enabled products), a source (`youtube`, `instagram`, `linkedin` or `other`) and an optional link slug. **Your link** changes as the choices change. It is the main link `/r/<code>`, or `/r/<slug>` when a slug is set, with the product, the source and the campaign in the query as `product`, `utm_source` and `utm_campaign`. With no campaign and no product, it is the plain link. Copying a link with a new slug saves the named link first, and copies it only when the save succeeds. A named link fixes its choices when it is saved, so a changed choice needs a new slug. The period is a from and to date, both included, picked in the header. The picker also offers the last 7, 30 or 90 days and this year. A period has at most 366 days. The default is the last 30 days, and a cleared period falls back to it. A date after today cannot be picked. Commission is not decided yet, so **Earnings per click** uses a sample rate of 50 USD for each paying customer.

### Review

A System Manager acts on an Affiliate in Desk. Each button shows only in the status that allows it.

| Action | From | To | Effect |
|---|---|---|---|
| **Approve** | Pending | Active | Sets the code at the first approval, and Reviewed By and Reviewed On. |
| **Reject** | Pending | Rejected | Stores the reason, and Reviewed By and Reviewed On. The reason is required. The applicant sees it. |
| **Disable** | Active | Disabled | Pauses the affiliate. Use it to stop an active affiliate. |
| **Enable** | Disabled | Active | Keeps the same code. |

Every action locks the row. When an operator approves or rejects a request that another operator already decided, nothing changes and Central says who decided first, for example "Already approved by admin@example.com". Any other action from the wrong status is refused.

The code has 8 characters from lowercase letters and digits, without the look-alikes `0`, `o`, `1`, `l` and `i`. Central draws again when a code is taken. If two approvals draw the same new code at the same time, the second one fails and the operator approves again.

### Named links

An Active affiliate adds a named link with `POST central.api.affiliates.create_link(slug, product, utm_source, utm_campaign)` and lists them with `get_links`. The link is `/r/<slug>`, for example `/r/bwh`. A slug has 3 to 32 lowercase letters, numbers and hyphens, and starts and ends with a letter or number. Central saves it in lowercase. An empty slug gets a random one. A slug is unique across all affiliates, first come first served, and cannot be any affiliate's main code. When two affiliates save the same slug at the same time, the second one is told that the slug is taken. An affiliate can have at most 100 links, and can add at most 30 in an hour. A link's product must be enabled, and a link must have a campaign.

### Affiliate link

An Active affiliate shares `/r/<code>` or a named link `/r/<slug>`. A named link fixes its product, source and campaign, and the query fills only what the link leaves empty. The main code takes them from the query, for example `/r/k7m2x9pa?product=raven&utm_source=youtube`, for example `/r/k7m2x9pa?product=raven&utm_source=youtube`. The code matches in any case. Central sends the visitor to `/dashboard/signup` with the `product`, `utm_source`, `utm_medium` and `utm_campaign` of the link. It ignores every other parameter, so the link cannot send a visitor to another site. The product key matches in any case. An unknown or disabled product is dropped, and the click counts for Frappe Cloud. The link answers GET and HEAD only, and the answer is never cached.

A click records an Affiliate Visit and sets the `central_affiliate` cookie. The cookie holds one visit for each product key, such as `{"raven": "m3x8k2qa", "fc": "t7w2p5nc"}`. A new click for a product replaces that product's visit and leaves the others. A click with the same affiliate, product and UTM values as the browser's visit for that product updates Last Clicked On instead of adding a visit. The cookie is HttpOnly, SameSite Lax, Secure on HTTPS, and lasts Affiliate Cookie Days. Central ignores a cookie that it cannot read or that names a deleted visit.

The visitor always reaches signup. Central records nothing when:

- the code is unknown or the affiliate is not Active
- the request is HEAD, has no user agent, or comes from a crawler or link preview
- the signed-in user is the affiliate
- the IP address made more than 60 counted clicks in the last hour
- Affiliate Cookie Days is 0

### Referral

Central credits a signup in two places. Both read the visit for the product key in the cookie. When the cookie has no visit for that product, they read the `fc` visit, because a plain link counts for any product. A link for the product wins over a plain link. A visit for another product is never used.

| When | Product key |
|---|---|
| The signup flow creates a new user's first Team (`central.api.sites.create_trial_team`) | The product of the current signup, from `signup_product`. An unknown or disabled product, or none, uses `fc`. A user who already has a Team gets no new Team and no referral. |
| A Team starts a product trial site (`central.api.sites.create_trial_site` with a product) | That product. Only when the Team has no earlier Site of that product, terminated sites included, and no earlier request for one. A trial without a product records nothing here. |

Central creates the Product Referral only when all of these are true:

- the cookie has a visit to use, and the visit exists and is for that product or for no product
- the visit's affiliate is Active now
- the last click is not older than Affiliate Cookie Days, checked on the server
- the affiliate is not a member of the Team
- the Team has no referral for that product yet

The referral copies the affiliate, the visit and the UTM values of the visit. Central then removes the entry it used from the cookie and keeps the others. The first referral for a Team and product is final. A later click on another affiliate's link records a visit and changes nothing else. A referral error is written to the Error Log, and the signup continues.

### Summary

An Active affiliate calls `GET central.api.affiliates.get_summary(from_date, to_date)`. Both dates are included, and the period has at most 366 days. Central counts from existing records and stores no totals.

| Number | Counts |
|---|---|
| Visited | Affiliate Visits created in the dates. A person who clicks links with different sources counts once for each. |
| Signed up | Product Referrals created in the dates. |
| Created a site | Of those referrals, the ones whose Team has a Site (of the referral's product, for a product referral). |
| Added billing | Of those referrals, the ones whose Team has an Active Payment Method. |
| Converted | Of those referrals, the ones whose Team paid a Billable Invoice with Amount Paid above 0 after the referral. An invoice the Team paid before the referral does not count. |

A later step implies the earlier ones, so a Team that paid also counts as Added billing and Created a site.

A Frappe Cloud (`fc`) referral converts only when its Team has no product referral from any affiliate. Otherwise the payment belongs to the product referral. When a Team has two product referrals, both convert when the Team pays. An invoice paid only with credit does not convert. A refunded invoice still converts.

Billing is in arrears, so a Team pays its first invoice some weeks after it signs up. A recent signup shows as not converted even when the customer will pay.

The answer holds `totals`, `previous_totals` (the same numbers for the period of the same length just before), `daily` (clicks, signups and paying signups for every day, 0 on a quiet day; a paying signup counts on the day it signed up), `by_link` (the named link, or `null` for the main code), `by_source` (by `utm_source`), `by_product`, `by_country`. The link and country of a signup come from its visit. An empty link, source, product or country is `null`. The answer never names a Team. Any other user, or an affiliate that is not Active, is refused.

### Retention

`GET central.api.affiliates.get_retention` shows how long the affiliate's paying customers keep paying. It is not tied to the period. A paying customer is a referred Team that converted, as in the summary. A customer counts in a month when it paid a Billable Invoice with Amount Paid above 0 in that month. Only payments after the customer's first referral by the affiliate count.

| Value | Meaning |
|---|---|
| Customers | Paying customers of the affiliate. |
| Active in the last 30 days, and in the last 90 days | Customers that paid an invoice in that time. The page also shows each as a percent of all paying customers. |
| Trend | Customers that paid in each of the last 12 months, oldest first. The page does not show it. |
| Curve | For month 1, 2, 3 and on, up to 12: of the customers whose first payment is at least that many full months back, the percent that paid in that month after their first payment or later. Month 1 is the month after the first payment. A customer still pays until its last paid month. Recent customers count only for the months they have had. The page shows the curve as a line, with the customer counts and the percent active in 30 and 90 days above it. |

## Configuration

| Central Settings field | Default | Meaning |
|---|---|---|
| Affiliate Cookie Days | 30 | Days a click on an affiliate link is remembered. A signup after this gets no referral. 0 stops recording clicks. |

## Known behavior

| Action | Result |
|---|---|
| Delete a Team that has a Product Referral | Refused. The referral keeps the team. |
| Delete an Affiliate Visit that a Product Referral links to | Refused. |
| Delete an Affiliate that has visits or referrals | Refused. Disable it instead. |
