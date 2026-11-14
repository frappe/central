# Credits and spend limits

Credits are money you pay in advance into your team's wallet. A spending limit is the most that everything your team runs can cost in a month, before tax. Taxes are added on top. Your limit comes from your trust tier, and the tier rises as you pay invoices.

::: info
You need the Owner, Admin, or Billing role to add credit. All billing roles can see the wallet and the limits.
:::

## Wallet credits

The wallet holds your prepaid credit. Each invoice uses credit first, before Frappe Cloud charges a payment method. The balance shows as **Wallet** in the summary panel and as **Prepaid credits** on the **Methods** card.

Credit that you add while an invoice is unpaid pays that invoice only when it covers the whole amount due, tax included. Otherwise the credit stays in the wallet, and Frappe Cloud does not split the invoice between credit and a payment method. If an automatic debit for the invoice was still pending at your bank and goes through after the credit paid the invoice, Frappe Cloud refunds that debit in full to its source.

### Add credit

1. Go to **Billing > Overview**.
2. In the summary panel, click **Add credit**. You can also click **Top up** on the **Methods** card on **Billing > Payments**.
3. Type an **Amount**, or click a preset amount.
4. Click **Continue to payment** and complete the payment.

<Screenshot name="billing/topup" alt="The Top up wallet dialog with an Amount field and preset amounts of 1,000, 5,000, 10,000, and 25,000 dollars" />

Frappe Cloud adds the credit to your wallet after the payment goes through. Add your billing details before you add credit.

After 5 failed card or UPI setups or wallet top-ups in a row that your bank declines, you must wait before you try again. See [When you see "Too many failed attempts"](/billing/payment-methods#when-you-see-too-many-failed-attempts).

### Credit for a large INR bill

A card or UPI can pay only up to its limit automatically, at most ₹15,000. The overview shows **Add credit before your payment date** when your card or UPI would be asked for more than that limit on the payment date. This also applies to automatic payments: your payment mode does not change until an invoice is charged. Frappe Cloud also sends an email 5 days and 2 days before the payment date.

The message asks for enough credit for your wallet to pay the whole bill, rounded up to the next ₹100. If you pay GST on top-ups, it also shows what that credit costs with GST, for example "Add ₹28,900 of credit to your wallet by 8 December 2026 (₹34,102 incl. IGST 18%)". The GST is named from your tax profile: IGST, or CGST and SGST when your state is the same as Frappe's. Click **Add credit** on the overview, or **Open billing** in the email, to open the top-up with that credit filled in. The dialog shows the GST and the same total to pay.

If earlier credit in your wallet came with no GST paid on it, the new top-up pays that GST too, so the credit asked for can be more than what your wallet is short. The message then says "This includes GST on earlier credit that had none."

The amount follows how your wallet pays an invoice:

- Credit you paid GST on pays the invoice amount before tax, and its GST pays the invoice GST. Promotional credit pays the invoice as it stands, tax included.
- Before the invoice is issued, your wallet pays what it can and the card or UPI pays the rest. The message goes away when what your wallet leaves is within the limit.
- After the invoice is issued, credit you add pays it only when the credit covers the whole amount due. The message goes away when your wallet covers the whole amount due, or when that amount is within the limit.

Promotional credit that expires before the payment date does not count. If you do not add credit, Frappe Cloud cannot charge the bill automatically, and the invoice stays unpaid until you pay it.

### Wallet history

Click **Wallet** in the summary panel to see each credit and debit and the balance. Click the download icon on a top-up to download its receipt.

## Trust tiers

Each team is on a trust tier. The tier sets two limits:

| Limit | Meaning |
| --- | --- |
| Spending limit | The most that everything your team runs can cost in a month, before tax. Taxes are added on top. |
| Resources | The most servers and subscribed services your team can run at one time. |

The **Limits** card shows your tier, what everything your team runs now costs a month before tax against the limit, and your resource count against the limit. This is the same figure that Frappe Cloud checks when you create or resize a server. It is not the projected bill for the cycle, which includes tax and can include usage.

<Screenshot name="billing/limits" alt="The Limits card on the t3 tier: 749.44 of 12,048.19 dollars limit running a month before tax, and 14 of 500 resources" />

### Move to a higher tier

Tiers rise automatically as you pay invoices. Each tier needs a number of paid invoices and a total amount paid. The first tier needs only a card or prepaid credit.

The **Limits** card shows what the next tier needs, such as **Paid invoices** and **Paid to date**, and how close you are. Click **All tiers** to see every tier, what it needs, and its limits.

<Screenshot name="billing/tiers" alt="The Limit tiers panel with tiers t0 to t3, what each needs to qualify, and each spend and resource limit" />

The tiers and amounts in your console depend on your billing currency. The console is the source of truth for your limits.

## When you reach a limit

Frappe Cloud checks your limits when you create or resize a server. It refuses the change when:

- The monthly cost of the new server, added to the monthly cost of what your team already runs, goes above your spending limit. Both costs are before tax. Taxes are added on top. Choose a smaller plan. The refusal shows the new cost, your limit, and what your servers already cost.
- You pay with credits only, and your credits do not cover the new monthly cost and your current costs. Credit you added pays the cost before tax, and the GST you paid with it pays the tax. Free credit pays the tax too, so it covers less before tax. Add credit or a payment method.
- Your team already runs the most servers that your tier allows. Terminate a server you no longer need.

When what your team runs reaches 80% of the limit, the amount on the **Limits** card turns amber.

To ask for a higher limit, click **All tiers**, then click **Contact support**.

## See also

- [How billing works](/billing/)
- [Payment methods](/billing/payment-methods)
- [Create a server](/servers/create)
- [Troubleshooting](/help/troubleshooting)
