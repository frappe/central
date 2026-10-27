# Signups

## Purpose

The Signups module holds what a new customer gets: the [Product](doctype/product/SPEC.md) they sign up for, the free trial and the welcome credit. Operators start with the [Trials operator guide](../../spec/TRIALS_OPERATOR_GUIDE.md).

## Welcome credit

Grant Welcome Credits is off by default, so no team gets a welcome credit: a product signup gets a free trial site instead, and every other server needs a payment method. When an operator turns it on, a Team gets the welcome credit when its first payment method becomes active, not at signup. The credit is granted once for each owner across all of the owner's Teams.

A Team that had a free trial gets no welcome credit, because the trial site is its free start. A card still converts its trial site. `is_welcome_credit_due` holds this rule.

| Billing Settings field | Value on a new install |
|---|---|
| Grant Welcome Credits | Off |
| Welcome Credit Amounts | 10 USD, 1000 INR |
| Validity (Days) | 60 |

A new install seeds these values once. Change them on an existing site in Billing Settings. A currency with no amount gets no credit. A staging trial team (Billing Settings, Provision Teams as Trial) still gets its credit at signup, because it runs servers on credit before it has a payment method.

### Operator credit

A System Manager can grant credit from the **Grant Credit** action on a Team, for example 100 USD to a beta user. The operator sets the amount in the Team's billing currency, the validity in days and a note. The credit is available at once. It counts as the owner's welcome credit, so the Team gets no welcome credit later.

## Trials

A trial site is a site from a Product's signup flow, for a Team that has no active payment method and has never paid. A direct Central signup has no free trial: it lands in the console, adds a payment method and buys its servers. Only a signup link with `?product=` opens the onboarding pages, and `create_trial_site` needs a product. It runs free for a set number of days. The trial state is on the Site, in the **Trial** section.

A Team has paid when it has a Subscription, or an Invoice that is not Draft or Cancelled. Such a Team buys its signup sites like any other server, also when its payment method has expired or failed. So a Team with unpaid invoices cannot open free servers.

### Configuration

| Field | Where | Meaning |
|---|---|---|
| Trial Days | Central Settings (Trials tab), and Product | Days a trial site runs from when Central records it. A Product with 0 uses Central Settings. |
| Trial Deletion Days | Central Settings (Trials tab), and Product | Days a stopped trial site is kept before its server is terminated. A Product with 0 uses Central Settings. |
| Trial Notice Days | Central Settings (Trials tab) | Days before the end date, and before the deletion date, that the warning email goes out. |

Example: Central Settings has Trial Days 7 and Trial Deletion Days 7. Product `raven` has Trial Days 14. A Raven trial runs 14 days, stops, and is terminated 7 days later.

### Operation

Central records the site when the region first reports its machine with an address, a few minutes after the request. The trial starts then. It does not wait for the customer to open the site, so a trial that the customer leaves also ends.

A free-trial server also boots with a Grove key from the pool [AI Settings](../services/doctype/ai_settings/SPEC.md) keeps, when the pool has one, so the site's apps can call AI before the team has AI of its own.

| Trial State | When | What Central does |
|---|---|---|
| Active | Central records the site and its creation request is a free trial | Sets Trial Ends On. When the Team added a payment method before Central recorded the site, the site converts at once. |
| Converted | Central records the site and its creation request is not a free trial | Nothing. The site is not a trial. |
| Ended | Trial Ends On is reached | Stops the server and sets Trial Deletes On. |
| Deleted | The server is Terminated: on Trial Deletes On, or when the customer terminates it earlier | On Trial Deletes On, asks for a normal terminate action each day until the server is Terminated. A server with termination protection on is kept, and Trial Error says why. Sets the state when the server is Terminated, so the owner can start a new trial at once. |

The `Trial` class in `central/signups/trial.py` owns these states. Every change goes through `Trial.move_to`, which refuses a change that its transition table does not allow. The daily job `central.signups.trial.run_trials` moves each site. It sends each email once and records the last one in Trial Last Notice.

| Event | Sent |
|---|---|
| `trial_unopened` | Once, from the day after the site is ready, when nobody has opened it. Not sent when a warning is due. |
| `trial_expiring` | Trial Notice Days before Trial Ends On, and again on the last day. |
| `trial_ended` | When the stop job has stopped the server, not when the trial ends |
| `trial_deletion_soon` | Trial Notice Days before Trial Deletes On |
| `trial_deleted` | When the server is terminated. Its button opens the signup page of the same product. |
| `trial_converted` | When a payment method converts the trial |

The `trial_expiring`, `trial_ended` and `trial_deletion_soon` emails link to the server's Upgrade dialog (`/servers/<server>?action=resize`). That dialog adds a payment method and, for an Ended trial, keeps the site. A payment method added on Billing does not keep an Ended trial.

A Product can add its own paragraph to each email and show its own logo and name. See [Product emails](doctype/product/SPEC.md#emails). These events are in the **Trial** notification category. A user can turn the email or the in-app notice for this category off in their notification settings. Each event goes to the Team members who hold `billing:view`.

A trial server usually sleeps when idle, and Atlas does not stop a sleeping VM. To end a trial, Central starts the server and then stops it. An explicit stop keeps the VM down, so traffic does not wake it.

### Limits

| Request | What Central checks |
|---|---|
| A trial site from the signup flow, Team that has no payment method and has never paid | The Team's owner has fewer open trial sites (Active or Ended), pending trial site creations, and provisioned trial servers whose site Central has not recorded yet, across all the owner's Teams, than Central Settings, Trial Servers Limit. A new Team gives no new trials. No credit is needed. Otherwise Central refuses with `TRIAL_IN_PROGRESS`, which names the open trial. |
| Any other server | A Team with an overdue invoice, or a subscription that is Past Due or Suspended, is refused with `PAYMENT_OVERDUE`. Otherwise credit covers the server's monthly rate, or the billing profile is complete and the Team has an active payment method, or the Team pays by Manual Checkout and has already paid one invoice by gateway. Otherwise Central refuses with `PAYMENT_METHOD_REQUIRED`. With Central Settings, Require Payment Method for Servers off, a complete billing profile is enough. |
| Start an Ended trial's server | Refused. The Team adds a payment method and then chooses Keep this site, which converts the trial and starts the server. |
| Resize a trial server | Not done. A trial server has no subscription. On an open trial, `central.api.servers.resize_server` (which also needs `billing:manage`) and `billing_api.change_plan` keep the plan in Conversion Plan on the Site and resize nothing. The plan must be one of the trial's plan choices. `get_composed_config` returns `trial` and `trial_plans`. |

### Signup with an open trial

`central.api.sites.get_open_trial(team)` returns the owner's oldest open trial across all the owner's Teams, or null. The signup page reads it before it asks for a site name, so it can offer that site instead. It returns `site`, `server`, `address`, `url`, `product`, `product_title`, `product_logo`, `state`, `ends_on` and `deletes_on`. While the first site is still being set up, it returns only `state` (Setting up) and the product fields. A caller who cannot view the trial's Team gets the same fields only, so a site of another Team is not named. It needs `server:create`.

| Open trial | What the customer can do |
|---|---|
| Active | Open the site, and install another product's app there. |
| Ended | Keep the site, or terminate its server. A terminated trial is Deleted at once, so a new trial can start. |

### Another product's app on the open trial site

`TrialAppInstall` in `central/signups/app_install.py` adds a product's app to the owner's Active trial site, so one free site runs both products. The enabled Product gives the app (Signup App), the title, the logo, the Setup Messages and the landing page.

| Step | API | What happens |
|---|---|---|
| Start | `install_trial_app(product, team)` | Central reads the site's apps from Pilot. When the site has the app, it returns `success` and no task. Otherwise Pilot queues the install, and Central adds a comment on the Site with the Pilot task. |
| Progress | `get_trial_app_install(site, task_id, product, team)`, a POST every 3 seconds | Returns `status` (queued, running, success, failed, or unreachable when the site did not answer this time), `queue_position` and `started_at`. |
| Open | `login_site(name, product)` | Signs in on the Product's Landing Route. |

| Failure | Customer sees | Operator sees |
|---|---|---|
| The site does not answer at start | "Your site did not answer. Wait a minute, then try again." | Error Log "Trial app install failed" |
| The site does not answer for 2 minutes of polls | "Your site stopped answering. Try again in a few minutes." | Nothing new. Pilot keeps the task. |
| The Pilot task fails | "CRM could not be installed on your site." with Try again and Open my site | Error Log and a comment on the Site with Pilot's reason |

### Server access

An open trial (Active or Ended) gives the customer the site, not the server. A free trial whose site Central has not recorded yet is locked too, because its creation request says it is a free trial. `VirtualMachine.require_server_access` refuses these routes with a permission error until the trial converts:

| Route | Entry point |
|---|---|
| Set the server's SSH keys | `VirtualMachine.set_ssh_keys` |
| Web console, SSH or TTY | `central.integrations.servers.get_console_url` |
| Pilot sign-in, also "Open server" in the site | `VirtualMachine.get_bench_login_url` |
| Snapshot, also the final snapshot on terminate | `central.api.snapshots.take_snapshot`, `submit_command` |
| Termination protection | `VirtualMachine.set_termination_protection` |
| GitHub connect for the server's Pilot | `GitHubConnectionAttempt.bind` |

A System Manager keeps access. A Team SSH Key sync skips a locked server, so its keys never reach it. The daily automatic snapshot skips a locked server too. A trial server starts with no SSH keys. Site sign-in (`claim_site`, `login_site`) stays open. The console registry returns `is_access_locked` on each server, so the console hides these actions.

`central.api.pilot.get_server_access` returns `is_locked` for the server of the calling Pilot credential. It is for Pilot, which must refuse the site's config edits and config downloads while the server is locked. A credential whose server is not linked yet reads as locked.

A team with a locked server also gets no LLM and no object storage, because both cost money. `central.signups.access.require_service_access` refuses `enable_ai` and `create_bucket`, the only ways in. The console shows the refusal message. A System Manager keeps access.

### Console

`central.billing.api.dashboard.account.get_billing_profile` returns `payment_method_required` and `welcome_credit` (`amount`, `currency`, `validity_days`, or null when the owner already had it). It also returns `open_trial`: the team's own oldest open trial (`state`, `server`, `product`, `product_title`, `plan`), or null. `server` is null for a caller without `server:view`. The Billing page and the onboarding payment step show it: an Active trial converts when the payment method is added, and an Ended trial is kept only from the Upgrade dialog. When a payment method is required, the New Server page shows a note and disables Create. Its **Add payment method** button opens the billing details dialog when they are missing, then the payment method dialog, on the same page. The welcome credit offer needs a billing currency, and the currency comes from the country (India pays in INR, every other country in USD). So the onboarding payment step asks for the billing country first and saves it to the billing profile. It fills India when the browser time zone is in India. It then names the welcome credit in that currency, says that adding a payment method does not charge it, and opens the same two dialogs, with the country already filled. On Billing, the main action for a new team is **Add card**. **Add credit** on the Wallet row tops up the prepaid wallet.

### Billing and conversion

A trial server has no subscription, so a trial creates no invoice. Central decides once, when the signup sends its creation request, whether the site is a free trial. It stores the answer in Free Trial on the Resource Action. Every later step reads that value and does not check the payment method again, so a card added or removed during creation does not change it. The daily backfill of missing subscriptions skips these servers too.

When a payment method of the Team becomes active, every Active trial site of the Team becomes Converted. An Ended trial stays Ended and stopped, so a card added for one product does not start and bill a site the customer left. To keep an Ended trial, a member with `billing:manage` chooses **Keep this site** in the console resize dialog (`central.api.servers.keep_trial_site`). It converts that one site and starts its server. Its deletion date applies until then.

Central converts the Active trials one at a time, oldest first. Each one must fit the Team's spending limit: the trust-tier cap minus the monthly rate of its running subscriptions and of its converted trials whose servers are not terminated and have no subscription yet. The check runs under a lock on the Team, so two conversions cannot use the same part of the limit. A trial whose plan does not fit stays Active, with the reason in Trial Error, and the console says that the plan is above the spending limit. The daily job goes through open trials oldest first and converts it once the limit is raised. Keep this site applies the same check.

A site becomes Converted in these steps:

1. Central records Trial Cost: the server's plan's monthly rate, divided by 30, for each day since Central recorded the site.
2. A running or sleeping server gets its subscription now. A stopped server gets it when it starts. A server on a trial plan gets it when it runs its paid plan, so the trial plan is never billed. Until then, `get_composed_config` returns `starting`, and the console resize dialog says the server is moving to its paid plan and checks again.
3. A background job moves a server on a trial plan to its paid plan with a normal resize, which also turns idle sleep off and starts the server. The resize has no subscription to re-lock, so the server opens its subscription on the paid plan when the resize is done. For a server on any other plan, the job turns idle sleep off in Atlas, and starts the server when it is Stopped. When the team pays while the trial's stop job runs, the stop job queues this job again, so the server does not stay stopped. When a resize of the server is pending, the job writes a Trial Error and stops, because both jobs change the server's power. The daily job sends the conversion again.

A plan marked Available on Trial is a trial plan. Only a free trial site starts on one, and every paid plan list leaves it out (`get_server_plans`). A trial on a trial plan converts onto a paid plan: the Site's Conversion Plan, which the customer picks in the in-app billing panel or the console Upgrade dialog, or else the cheapest plan in the trial's plan choices (`Trial.get_conversion_plan`). The plan choices are the paid plans that the team may resize to, no smaller than the trial plan, cheapest first (`Trial.get_plan_choices`). A trial on any other plan converts on it.

A trial is priced at the catalog rate of the plan it converts to, in the team's currency and the server's region, which is the rate its subscription charges. The rate reserved on the creation request is not its price: the customer accepted no quote at signup, the currency at signup is a guess before the billing profile exists, and a subscription keeps its opening rate. The spending-limit check, the rate held for a starting server, Trial Cost and the Upgrade dialog all use this one rate (`Trial.get_monthly_rate`).

The plan menus of a trial server (the plan choices, console resize and in-app Change plan) leave out every plan with less vCPU or memory than the plan the trial was created on, because the product site needs at least that much (`get_trial_plan_floor`).

A Deleted trial is not converted, because its server is gone. Its Trial Cost runs to Trial Ends On.

### Upgrade dialog

The console's Upgrade dialog on a trial server lists the trial's plan choices with their monthly rates, with the Conversion Plan or the cheapest one selected. **Add payment method**, **Keep this site** and, for a held trial, **Use this plan** first save the selected plan. After the payment method is added, the dialog checks the trial again every 5 seconds for 2 minutes. While the server moves to its paid plan, the dialog says so. An Ended trial is only kept: **Keep this site** moves the server to the selected plan and starts it.

### In-app status

`central.billing.api.billing_api.get_billing_summary` returns `trial` for the site on the calling server: `state` (Active or Ended), `can_keep` (Ended, the Team has an active payment method, and the caller has `billing:manage`), `held` (Active, and the Team has an active payment method, so the spending limit holds it), `ends_on`, `days_left`, `deletes_on` and `plan`. `plan` is the plan the site converts to: `name`, `title`, `monthly_rate` (the plan's catalog rate in the team's currency and the server's region, which the subscription charges) and `currency`, or null when the site has no creation request. `trial` is null when the site has no open trial. `plan_change` is the pending resize of the server, such as the move to the paid plan: `plan` (its title) and `progress_url`, the waiting page. It is null when no resize is pending. On an open trial, `get_plan_options` returns the trial's plan choices with `selected`, the plan the site converts to, and `change_plan` keeps the chosen plan. The in-app billing panel shows these. On a server with several sites, the caller passes `site`, the Site's name. Without it, Central refuses the call.

### Desk

On a Site with an open trial, a System Manager has a **Trial** menu: **Extend Trial** adds days and starts an Ended trial again without the AI key its end revoked, **End Trial Now** ends an Active trial today and revokes its AI key at Grove, and **Retry Trial Step** runs today's step again after a Trial Error. On a Converted site, it sends the conversion job again. Each action leaves a comment on the Site. A trial that converts hands its AI key to the team at Grove in the background, best effort: three attempts, then the AI Trial Key record and the Site say it failed, the key is revoked and the team creates its own. The **Trial Sites** report counts trial sites and their cost by product, month and state.

### Failure

When a stop, a terminate, or the conversion job fails, Central writes the reason in Trial Error on the Site and an Error Log, and the daily job tries again the next day. The daily job includes Converted sites that have a Trial Error. While a trial is Ended and its server is not Stopped, the daily job sends the stop again.

### Operator alerts

`central.signups.alerts.alert_failed_signups` runs every hour. When a signup site creation became Failed or Timed Out in the last hour, it sends one message that lists them, through the operator alert channel in Billing Settings (Raven, or email as a fallback). A signup should never fail, so one failure is enough. The check adds nothing to the signup path.
