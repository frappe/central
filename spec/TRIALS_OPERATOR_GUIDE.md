# Trials Operator Guide

This guide is for the person who runs free trials and welcome credit from Desk. For the full behavior, read [Signups](../central/signups/SPEC.md).

## How a trial works

1. A customer signs up and gets a trial site. The site is free. It sleeps when nobody uses it.
2. The trial ends after **Trial Days**. Central stops the server.
3. **Trial Deletion Days** later, Central deletes the server and its data.
4. Central emails the team before the end, at the end, before deletion and at deletion.
5. If the team adds a payment method at any time, the trial becomes a paid site. Billing starts, and a stopped server starts again.

A team without a payment method can only have free trial sites. To create any other server, it must add a payment method.

## Before launch: check these settings

| Where | Field | Value |
|---|---|---|
| Billing Settings | Grant Welcome Credits | Off. A product signup gets a free trial site, not credit. |
| Billing Settings | Welcome Credit Amounts | Used only when Grant Welcome Credits is on |
| Billing Settings | Validity (Days) | 60 |
| Billing Settings | Provision Teams as Trial | Off. This is for staging only. |
| Plan | Available on Trial | On for each active plan that signup may select. The cheapest eligible marked plan is selected. Its disk must fit the trial image. A marked plan is a trial plan: no paid server is created on it or resized to it, and the customer never sees its price. |
| Central Settings, Trials tab | Trial Days | 7 |
| Central Settings, Trials tab | Trial Deletion Days | 7 |
| Central Settings, Trials tab | Trial Notice Days | 2 |
| Central Settings, Trials tab | Trial Servers Limit | 1, counted across all teams of one owner |
| Central Settings, Limits tab | Require Payment Method for Servers | On |
| Central Settings, Trials tab | Trial Idle Shutdown (Minutes) | 10 |
| Region | FrappeMail Service | Enabled. Keep enough free mailboxes, because an empty pool stops new trials. |

A Product can have its own Trial Days and Trial Deletion Days. Leave them at 0 to use Central Settings.

A trial gives the customer the site only. SSH, the web console, Pilot and snapshots open when the trial converts. An operator keeps them. See [Server access](../central/signups/SPEC.md#server-access).

Only a product signup gets a free trial. A direct Central signup adds a card and buys its servers. The entry Trust Tier Level's spending cap must be at least the monthly price of the cheapest paid plan, because a trial on a trial plan converts onto a paid plan. Otherwise a card leaves the trial held instead of converting it.

## Common tasks

| Task | What to do |
|---|---|
| Find trial sites | Open the **Site** list. Filter by **Trial State**. Blue is Active, orange is Ended, green is Converted, gray is Deleted. |
| Give a customer more time | Open the Site. Click **Trial > Extend Trial** and enter the days. An ended trial starts again without its AI key, which was revoked when it ended; the Site says so and the team creates a key in the dashboard. |
| Give a trial more AI spend | Open the **AI Trial Key** record of its server (status Assigned). Click **Raise Cap** and enter the new USD cap; Grove applies it on its next sync, a minute or two. A key that is converting, converted or revoked is not raised here: a converted key is the team's, capped from its dashboard. |
| End a trial now | Open the Site. Click **Trial > End Trial Now**. The server stops today and its AI key is revoked. |
| A customer converted; where is their AI key | Open the **AI Trial Key** record of their server. **Converted**: the team holds the same key at Grove, titled by the site, and sees it in the dashboard. **Conversion Failed**: Grove refused or could not be reached three times; the key is revoked (the **Revoked** box ticks once Grove has it, retried hourly until then) and the team creates its own key in the dashboard. The record's **Last Error** is what Grove answered; the Error Log named "Trial key converting failed" has the traceback. |
| Fix a failed trial step | The Site shows the error in red at the top. Click **Trial > Retry Trial Step**. If it fails again, open the Error Log named "Trial step failed". |
| Give a beta user credit | Open the **Team**. Click **Grant Credit**. Enter the amount in the team's currency, the days it is valid, and a note. The team gets no welcome credit after this. |
| Let a team create servers without a card, for a demo | Turn off **Require Payment Method for Servers** in Central Settings. Turn it on again after the demo. |
| See what trials cost | Open the **Trial Sites** report. It shows sites by product, month and state, with their cost. |
| See a team's trials | Open the Team. The **Site** link in Infrastructure lists its sites. |

## What the customer sees

| When | Customer sees |
|---|---|
| New Server page, no payment method | A note at the top: add a payment method to create servers, and get the welcome credit when it is on. Create is off. **Add payment method** opens the payment dialog on the same page. |
| Onboarding, payment step | A **Billing country** field, saved when picked, which sets the currency. Then the welcome credit offer in that currency when it is on, that adding a payment method does not charge it, and an **Add payment method** button. It asks for the other billing details first when they are missing. |
| Trial ending, ended, deletion soon, deleted | An email and a notice in the **Trial** category. Customers can turn these off in their notification settings. |
| Site's in-app billing panel | A notice above the plan with the days left and the end date, and one **Upgrade** button. Upgrade shows the paid plans with the cheapest one selected, then the billing details when they are missing, then the payment step. Adding a payment method converts the trial: the server moves to the chosen plan, billing for that plan starts, and full server access opens. |
| Console resize dialog on a trial server | The same plan list, then an **Add payment method** button. |
| Console resize dialog on an ended trial, team has a card | The deletion date and, for a member with `billing:manage`, a **Keep this site** button. A card does not restart an ended trial by itself. Keep this site moves the site to the chosen plan and starts it. |
