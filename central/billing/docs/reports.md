# Billing reports and dashboards

## Purpose

This page lists every billing report and Insights dashboard, and the question each one answers. Use it to find the right view when you monitor billing or investigate a problem.

## Where to find them

- Desk: the Billing sidebar groups the reports below under the same headings. Open a report at `/desk/query-report/<Report Name>`. All reports need the System Manager role.
- Insights: the sidebar's Dashboards section opens each dashboard. The app ships them in `central/billing/insights_workbook/billing/billing.json`, and `bench migrate` installs them. Each dashboard has a Detail line that links the reports behind its tiles.

## Rules every report follows

- Money is shown per currency. A report never adds INR and USD in one column, total or card.
- Bare metal cost is in INR. USD revenue counts toward a margin at Billing Settings > Reports > USD to INR Rate for Reports. A report filter can give another rate. At 0, USD revenue is left out.
- A month filter reads one billed month. Empty reads the last closed month.

## Data the reports need

| Data | Where to set it | Used by |
|---|---|---|
| Monthly cost and vCPUs of each machine | Metal Server (mandatory) | every capacity and profitability report |
| Atlas host ID of each machine | Metal Server > Link Atlas Host | per-machine reports |
| Host reserve and CPU overcommit | Metal Server > Sellable Capacity | Bare Metal Capacity, Stranded Capacity, VM Packing Matrix, Capacity Forecast |
| Ownership, model, purchase, warranty, repairs | Metal Server > Lifecycle | Bare Metal ROI, VM Packing Matrix |
| Our cost per unit of a service | Resource Type > Our Cost per Unit | Service Profitability, Customer Profitability |
| Telemetry source of a region | Region > Telemetry Data Source | every column that says Used |

Used CPU, memory, disk and bandwidth come from the region's telemetry. Only servers that run the Pilot agent report guest usage. A report says how many servers it could not measure.

## Dashboards

| Dashboard | Use it to |
|---|---|
| Cloud Overview | See the whole business on one page: MRR, revenue, gross profit, growth, customers who pay, servers that pay nothing, machines, capacity used and idle cost. |
| Billing Health | See the state of billing: run rate, money still to collect, payment success, failed and stuck payments, stuck webhooks, accounting sync failures, held invoices and past due subscriptions. |
| Billing Day | Watch the monthly run for the month that just closed: invoices drafted and settled, how each settled, failures, run errors, stall signal, run time, time to sync, and run history. |
| P&L | See revenue, bare metal cost, gross profit and margin by month, growth, a 6-month forecast, money against credit, and refunds and disputes. |
| Unit Economics | See bare metal cost against what servers earn, by region, with a drill-down per machine and per team. |
| Bare Metal Yield | See what the sellable bare metal could earn at the rate card, what it earns, and how much is not earned because of unsold capacity, servers used free and discounts, and what servers that pay nothing cost in bare metal. |
| First Payment | See how many teams try to pay for the first time, how many fail, why they fail, how many recover and how, and which teams are lost. It also shows how invoice payment retries succeed. See [How the first payment is tracked](#how-the-first-payment-is-tracked). |

## Revenue

| Report | Question it answers |
|---|---|
| MRR and YTD Revenue | What is the monthly recurring revenue, and the revenue for the year so far? |
| Invoice Register | Which invoices were raised, for whom, for how much, and in which status? |
| Billing Projection | What is a group of teams about to be billed, from the latest projection batch? |
| Services Revenue | How much revenue comes from metered services such as AI tokens, email and PDF? |
| Cluster-wise Revenue | How much revenue does each region earn? |
| Atlas-based Revenue | How much revenue does each Atlas region earn, and what share of its currency's total is that? |
| Monthly Usage vs Invoiced | Did every metered unit reach an invoice? |
| Metered Add-ons | What does each metered add-on include, and what does it charge above that, per currency? |

## Profitability

| Report | Question it answers |
|---|---|
| Unit Economics | Grouped by who pays, region or team: what is the bare metal cost, the list value, the cash revenue and the margin? The Idle Capacity row closes the total to the metal bill. |
| Customer Profitability | Who makes us money? Revenue by VMs and services, direct cost, gross profit and margin per team, with allocated and used vCPUs and memory. Group by Server or Service, or filter one team, to drill down. |
| Service Profitability | Which services to push, fix, reprice or drop? Revenue, direct cost, gross profit, margin, customers and usage per service, with price and cost per unit. |
| Plan Performance | Which plans are best? Servers, customers, MRR, bare metal cost, margin and CPU used per plan, and revenue per unit of the resource the fleet runs out of first. |
| Metal Server Profitability | Is each machine earning its cost? Its whole monthly cost against what its servers pay, with allocated and used CPU and memory. |
| Free vs Paid Consumption | What do servers that pay nothing cost us? Servers, allocated and used resources, revenue and bare metal cost per machine and who pays. |
| Bare Metal ROI | Do the hardware economics work? Purchase, running and repair cost to date, revenue earned, gross profit, payback months, ROI, age, downtime and warranty. |
| Bare Metal Yield | Of what the sellable bare metal could earn, how much does it earn? Potential revenue, cash revenue, yield and the gap to unsold capacity, servers used free and discounts, per region or per machine. Also what servers that pay nothing cost in bare metal. |

## Capacity

| Report | Question it answers |
|---|---|
| Region Capacity | How much bare metal does each region have, how much do live servers hold, and what does the idle part cost? |
| Bare Metal Capacity | How full is each machine, really? Physical, reserved, sellable, allocated (with Atlas's platform servers), used and remaining, per resource. |
| Server Inventory | Which servers are live, who owns and funds each one, what does it list at, what does it earn and what is its margin? |
| Allocation vs Usage | Who buys capacity they do not use? Allocated against measured CPU, memory, disk and bandwidth per server. |
| Stranded Capacity | What stops us selling more? The resource each machine runs out of first, how much of the others it strands, and that stranded capacity priced at the component rate card. |
| VM Packing Matrix | How many servers of each plan fit on a machine of each model, and which resource limits it? |
| Capacity Forecast | When do we buy the next machine, and what shape? Remaining capacity against recent growth, months left, run-out and buy-by dates, and the machine shape new demand needs. |

### How cost, funding and capacity are worked out

- A region's monthly cost is the sum of `cost_per_month_inr` on its Active Metal Servers. A live server carries its vCPUs times the region's cost per vCPU.
- A metered line costs its quantity times its Resource Type's cost per unit. A service whose Resource Type has no cost shows cost 0.
- Who pays is checked in this order, and the first match wins: Our Own Team (Tax Profile marked internal), Free Trial (the server runs a free trial site), Paying Customer (an active payment method, bought credit or a paid invoice), Not Paying Yet (anything else).
- Sellable capacity is physical less the host reserve. vCPUs are then multiplied by the CPU overcommit ratio.
- Potential revenue prices each sellable vCPU, GiB of memory and GiB of disk at the region's INR component rate card (Resource Types Compute, Memory and Disk). A resource with no INR rate counts at 0.
- Yield is cash revenue divided by potential revenue. Potential revenue is unsold plus used free plus discount plus cash revenue. Unsold is the rate card value that no Central server holds, so platform servers count in it. Used free is the rate card value of servers that do not pay. It is revenue we do not earn, not a loss: what those servers cost us is their vCPU share of the metal bill, shown as Cost of Servers That Pay Nothing. On a machine row that share is of the machine's own bill. Discount is the rate card value of paying servers less what they pay, and is below 0 when they pay more than the rate card.
- Allocated capacity is what Atlas reports for the host, its own platform servers included, when telemetry answers. Otherwise it is the sum of Central's servers placed on the host.
- A server belongs to a machine when the server's `atlas_host_id` matches the machine's. Atlas sends a server's host in its `vm.state` webhook: when it records the server, when the state changes and when the server moves.
- Readiness checks R1 (a region with servers but no priced metal) and R2 (a server on no known machine) feed the daily audit and the operator alerts.

## Collections

| Report | Question it answers |
|---|---|
| AR Collections Aging | How much is still to collect, and how many days past due is it? |
| Collection Outlook | Which teams are about to be suspended for non-payment, and on what date? |
| Failed Payments | Which payment attempts failed, and why? |
| Gateway Payment Success Ratio | What share of attempts succeed on each gateway, month by month? |
| Payment Method Mix | Which payment methods do teams use, in which state, and how many need authorisation again? |
| Dunning Recovery | Of the invoices that became overdue, how many were paid later? |
| Involuntary Churn | Which teams were suspended for non-payment, and which came back? |
| Refunds Report | Which refunds were made, to where, and for how much? |

## Credits and growth

| Report | Question it answers |
|---|---|
| Credit Wallet Movements | What went in and out of each wallet, and why? |
| Team Credit Balance | How much credit does each team hold now? |
| Internal Usage and Waivers | What did our own teams use, and how much was waived? |
| New Signups | Which teams signed up, and how far did each get: billing profile, payment method, first payment? A first payment is money the customer paid: an invoice paid by the gateway or by paid-in credit, or a credit top-up. Welcome credit alone does not count. |
| Trial Sites | How many trial sites started per product and month, how did they end, and what did they cost? |

### How the first payment is tracked

A team tries to pay when it adds a card or mandate, orders credit, or pays an invoice. The First Payment dashboard groups each team by its first try month and puts it in one outcome:

| Outcome | Rule |
|---|---|
| Paid first time | The team paid before any failure. |
| Method added, not billed yet | The team added a working method before any failure, and has not paid yet. |
| Abandoned setup | The team started a setup, never finished it, and had no failure. |
| Recovered | The team failed first, then paid within 30 days of the first failure. |
| Fixed method, not billed yet | The team failed first, then added a working method within 30 days. The dashboard counts it as recovered. |
| Window still open | The team failed first less than 30 days ago and has not recovered yet. |
| Lost | The team failed first and did not recover within 30 days. |
| Not billed directly | The team is internal (Tax Profile marked internal). |

A failure is any of these:

- A card setup that failed at the gateway. The Payment Method keeps the code and adds a `Payment Method Setup Failed` Billing Event.
- A card check or mandate confirmation that failed. The Payment Method moves to Failed with the code.
- A declined payment on a Top-up Order. The order keeps the last code and stays open, and each decline adds a `Top-up Order Declined` Billing Event with its code.
- A failed Payment Attempt on an invoice.

A payment is money the customer paid: an invoice paid by the gateway or by paid-in credit, or a credit top-up. Welcome credit does not count. An invoice payment is dated by the invoice's `paid_at`. A setup that the customer leaves is kept as a Cancelled Payment Method with the reason "setup abandoned".

A month is final 30 days after it ends. Every failure keeps the gateway's failure code and, where the bank gives one, its decline code. Use **Payment methods that failed** and **Declined top-ups** in the dashboard's Detail line to open the records.

## Billing health

| Report | Question it answers |
|---|---|
| Billing Invariant Violations | Which billing rules are broken now? This covers money invariants and readiness checks. Use the Summary view for a count per check. |
| Webhook Lag | How long do gateway webhooks take from receipt to processing? |
