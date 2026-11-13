# Invoices

An invoice lists what your team used in one billing cycle and what it owes. Go to **Billing > Invoices** to see, download, and pay your invoices.

::: info
You need the Owner, Admin, or Billing role to see invoices. Only roles that can manage billing can pay an invoice.
:::

## Find an invoice

The list shows each invoice with its period, invoice number, status, and amount. The newest invoice is first.

<Screenshot name="billing/invoices" alt="The Invoices page with monthly invoices from January to October 2026, each marked Paid" />

- Type a period or an invoice number in the search box.
- Use the **All status** menu to show only **Outstanding**, **Paid**, or **Overdue** invoices.
- Use the **Any date** menu to show the last month, the last 6 months, or the last year.

## Invoice statuses

| Status | Meaning |
| --- | --- |
| `Outstanding` | The invoice is not paid yet. Before it has a due date, it is being prepared and you cannot pay it. After it is issued with a due date, Frappe Cloud collects it from your credits and payment methods. |
| `Paid` | The invoice is paid in full. |
| `Overdue` | The invoice is past its due date and still unpaid. Pay it to keep your servers running. |
| `Waived` | Frappe Cloud cancelled the amount. You do not need to pay it. |
| `Cancelled` | The invoice was cancelled. |

An `Outstanding` invoice can stay without a due date while your billing details are not complete. Add your billing details to issue it.

## See an invoice

Click an invoice to open it. The panel shows:

- The invoice type, the period, and the due date.
- Each server and service with its plan, its dates, and its amount.
- The subtotal, the credits applied, the tax, and the total.
- How and when the invoice was paid.
- **Activity**: each payment attempt and its result.

<Screenshot name="billing/invoice" alt="An invoice panel for September 2026 with each server, its plan, and its amount" />

### How the tax is named

Each amount that includes tax names the tax. Teams in India see one of these names:

| Name | When |
| --- | --- |
| `IGST 18%` | Your billing state is not the state Frappe Cloud bills from, or your billing profile has no state. |
| `CGST 9% + SGST 9%` | Your billing state is the state Frappe Cloud bills from. |
| `No GST (SEZ)` | Your GSTIN is for a unit in a Special Economic Zone, and the GSTIN is active. The invoice shows the reason for zero tax. |

An amount that includes tax shows it after the amount, for example `₹11,800.00 (incl. IGST 18%)`. An SEZ amount shows `₹10,000.00 (SEZ supply, no GST)`. This applies to the payment schedule and the payment emails. In the invoice list, hover over the total to see the tax it includes. An issued invoice keeps its tax rate and its SEZ zero rating. It also keeps the billing state it was issued with, so it shows IGST or CGST + SGST as it was issued. A forecast, and an invoice issued before invoices recorded the state, follow your billing state today. In **Wallet history**, a top-up shows the GST paid on it, for example **GST paid: ₹180.00 (IGST 18%)**. This is the GST of that top-up, and it does not change when your tax changes later.

## Download an invoice

Click the download icon on the invoice row or at the top of the invoice panel. The PDF is your tax invoice.

The PDF is ready only after the invoice is issued. Until then, the download icon is disabled. You can download up to 30 invoices in one hour.

## Pay an outstanding invoice

Frappe Cloud tries to collect each invoice automatically. Pay by hand when an issued invoice is still `Outstanding` or `Overdue`, for example after a card is declined. You can pay an `Outstanding` invoice only after it has a due date.

1. Go to **Billing > Invoices**.
2. Click the `Outstanding` or `Overdue` invoice.
3. Click **Pay** with the amount, such as **Pay $683.11 now**.

The charge uses your saved payment method. While the bank confirms the payment, the panel shows **Waiting for your bank to confirm the payment…**. The status changes to `Paid` when the payment is confirmed.

When an invoice is unpaid, **Billing > Overview** shows a banner with the amount and a **Pay now** button. The banner is amber for an outstanding invoice and red for an overdue invoice.

## When a payment fails

Frappe Cloud charges an invoice on its payment date. When the charge fails, Frappe Cloud tries again every 2 days until the invoice due date, and sends a notification with the reason. When no retry fits before the due date, Frappe Cloud tries once more 24 hours after the failed charge. After the last retry, the invoice becomes `Overdue`. While your bank has not confirmed a charge, the invoice does not become `Overdue`, and the billing summary shows **Payment in progress**. On the day before the suspension date, every unpaid invoice becomes `Overdue` and you get a notification, also when your bank has not confirmed a charge yet. If the invoice stays unpaid, Frappe Cloud stops the team's servers on the 15th of the month. The data on the servers is kept. When you pay the invoice, Frappe Cloud starts the servers again.

An invoice is issued on the 1st and is due on the 8th, or on the payment date when that is later:

| Payment date | Retries | Servers stop on |
| --- | --- | --- |
| 1st | 3rd, 5th, 7th | 15th |
| 3rd | 5th, 7th | 15th |
| 5th | 7th | 15th |
| 6th | 8th | 15th |
| 7th | 8th | 15th |
| 8th | 9th | 15th |
| 10th | 11th | 15th |

If the invoice is issued late, for example after you add missing billing details, and its due date is on or after the 15th, the servers stop 7 days after its due date.

### When a payment is still in progress near the suspension date

You can add credit to your wallet to avoid suspension. When the wallet covers the full amount of an unpaid invoice, the credit pays the invoice at once, also while your bank has not confirmed a charge. If the bank confirms that charge later, Frappe Cloud refunds the full charge to the payment method and sends you a notification. The refund can take a few days to reach your account.

::: warning
Pay an overdue invoice as soon as you can. Stopped servers make your sites unavailable.
:::

To fix a failed payment, [add another card](/billing/payment-methods#add-a-card) or move a working card up the order, then pay the invoice.

## See also

- [How billing works](/billing/)
- [Payment methods](/billing/payment-methods)
- [Credits and spend limits](/billing/limits)
- [Troubleshooting](/help/troubleshooting)
