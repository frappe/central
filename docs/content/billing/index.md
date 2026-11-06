# How billing works

Frappe Cloud bills your team once a month, in arrears, for the servers and services it used in that calendar month. Go to **Billing > Overview** to see what you spend now, what you spent before, and how you pay.

::: info
You need the Owner, Admin, or Billing role to see billing. Members with other roles do not see **Billing** in the sidebar.
:::

## The billing cycle

A billing cycle is one calendar month, from the 1st to the last day. Charges add up during the month. After the month ends, Frappe Cloud issues an invoice for it and collects the payment.

Each invoice is paid in this order:

1. Prepaid credits in your wallet, on the invoice date.
2. Your payment methods, on the payment date, in the order shown under **Methods** on **Billing > Payments**. When one fails, the next one is tried.

The payment date is a day from the 1st to the 10th of the month. The default is the 1st. When the invoice is issued after that day, the payment method is charged on the invoice date. To pay an issued invoice before its payment date, open it and click **Pay *amount* now**. Only a user with the Owner, Admin, or Billing role sees this button. For UPI Autopay and other Indian mandates, Frappe Cloud sends a pre-debit notice no earlier than one day before the payment date, and charges 24 hours after the notice. When the payment date is the 1st, the notice goes out on the 1st and the charge is on the 2nd.

You do not need to pay a normal invoice by hand. See [Invoices](/billing/invoices) for an invoice that stays open.

## What you pay for

| Charge | How it is billed |
| --- | --- |
| Servers | A monthly rate set by the server's plan. On the day a server is created, resized, or stopped, each plan is billed for the hours it ran on that day. The invoice shows each server, its plan, and the dates it was billed. |
| Metered services | Usage, such as AI tokens. The amount is final when the month ends. |
| Add-ons | Subscriptions such as storage buckets and paid snapshots. |
| Tax | Added on each invoice for the tax region in your billing details. |

## The summary panel

The panel at the top of **Billing > Overview** shows the current cycle.

<Screenshot name="billing/summary" alt="The billing summary: October cycle, 650.58 dollars so far, bills in 7 days, a spend limit of 12,048.19 dollars on the t3 tier, and the next payment, wallet, payment method, and next invoice date" />

| Item | Meaning |
| --- | --- |
| Cycle and amount | The projected total for this cycle with tax, and the days until it is billed. Below it are the amount before tax and the tax. Click **See breakdown** to see each line. |
| Spend limit | The most your team can spend in one cycle on its current tier. Click the tier to see all tiers. See [Credits and spend limits](/billing/limits). |
| Due now | The amount of your unpaid invoices. This row shows only when an invoice is unpaid. |
| Payment in progress | The date Frappe Cloud started a charge that your bank has not confirmed yet. This row shows from the day of the charge until the bank confirms or refuses the payment, or until the suspension date. |
| Next retry | The date Frappe Cloud tries the payment again. This row shows only after a payment date passes and the invoice is not paid. |
| Suspends on | The date your servers stop if the invoice stays unpaid. This row shows when no retry is left. It also shows below **Payment in progress** when the invoice is overdue. To avoid suspension, add credit to your wallet. See [When a payment is still in progress near the suspension date](/billing/invoices#when-a-payment-is-still-in-progress-near-the-suspension-date). When your team is already suspended, the row shows **Suspended since** and the suspension date. |
| Wallet | Your prepaid credit balance. Click the history icon to see its history. Click **Add credit** to top up. |
| Payment method | The payment method that is charged first. |
| Next invoice | The date of the next invoice. |
| Next payment date | The next scheduled payment date. When an unpaid invoice passes its payment date, this row shows the payment date of the next invoice. |

To change the payment date, click the calendar icon (**Change payment date**) next to **Next payment date**. The **Payment schedule** panel opens. It also shows the amount due, the date of the next charge or retry, the payment method that is charged, and the dates of each step if the invoice stays unpaid. Select a day from the 1st to the 10th of the month and click **Save payment date**. You can change it at most twice in a billing cycle. You need the Owner, Admin, or Billing role. Wallet credit still applies on the invoice date. A change does not move the payment date of an invoice that is already issued.

A payment date from the 1st to the 6th gets a retry every 2 days until the invoice due date. A later payment date gets one retry, 24 hours after the failed charge. When you select a later day, the form shows a warning. In both cases, your servers stop on the 15th of the month if the invoice stays unpaid. See [When a payment fails](/billing/invoices#when-a-payment-fails).

Frappe Cloud sends these payment emails to team members who can see billing:

| Email | When |
| --- | --- |
| Invoice is ready | An invoice is issued with an amount to pay after wallet credit. It shows the total, the credit used, the amount to charge, the payment date, and the payment method. If the team has no payment method, it asks you to add one. |
| Payment due tomorrow | One day before the payment date. Frappe Cloud does not send it for an Indian mandate, which gets a pre-debit notice instead. |
| Payment date changed | You change the payment date. It shows the new day and the date of the next charge. An invoice that is already issued keeps its payment date. |

### Budget alerts

Click the bell icon on the summary panel to set a budget alert. Type an amount and click **Set alert**. The amount excludes tax. The team gets a notification when the projected spend for the cycle, before tax, goes above that amount. Set `0` to turn the alert off.

## The spend chart

The **Spend** card shows what your team was invoiced in the last 3, 6, or 12 months. Click **3M**, **6M**, or **12M** to change the period.

<Screenshot name="billing/spend" alt="The Spend card with 12 months of invoiced amounts, the totals for invoiced, monthly average, paid by credits, and tax, and the spend by product" />

- The top row shows the total invoiced, the monthly average, the amount paid by credits, and the tax.
- The dark bars are invoiced months. The light bar is the current cycle.
- **By product** splits the total, such as servers and AI tokens.
- Click the download icon to export the data as a CSV file.

## Other cards on the overview

| Card | Use it to |
| --- | --- |
| **Limits** | See your tier, your spend this cycle against the limit, and your resource count. |
| **Subscriptions** | See each server and service you pay for and its cost this cycle. |
| **Breakdown** | See what the team was invoiced by product and by region for the chosen period. |

## Other billing pages

| Page | Use it to |
| --- | --- |
| **Billing > Payments** | Add, order, and remove payment methods on the **Payment methods** card. See [Payment methods](/billing/payment-methods). See and edit who invoices are billed to, the billing email, phone, currency, and GSTIN on the **Billing details** card. |
| **Billing > Invoices** | See each invoice. Open the **Statement** tab to see the invoices and payments for a period, to reconcile with your own records. Tax invoices are issued separately. |
| **Servers** | Click **Stop all** to stop every running server in the team. Sites are unavailable while the servers are stopped. Data is kept, and you can start the servers again. |

## What next

**[Add a payment method](/billing/payment-methods)**: add a card so that Frappe Cloud can collect each invoice.
