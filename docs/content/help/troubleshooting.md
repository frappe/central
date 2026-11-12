# Troubleshooting

This page lists common problems with teams, billing, and servers, and how to fix them. Each problem starts with the message or the behavior that you see.

## Team and access

| Problem | Fix |
| --- | --- |
| You do not see **Billing** in the sidebar, or a button such as **Invite** is missing. | Your role does not include that permission. Ask an Owner or Admin to change your access. See [Roles and permissions](/team/roles). |
| **This user is already a team member.** | The person is already on the team. To change their role, use **Manage access**. |
| **This person already has a pending invitation.** | Open the **⋮** menu on the invitation row and click **Resend**. |
| **You have sent too many invitations. Try again in an hour.** | Wait one hour, then send the rest. |
| **This invitation was sent less than 5 minutes ago. Try again later.** | Wait a few minutes, then click **Resend** again. |
| **This invitation has expired.** | Ask a team Admin to resend the invitation. A resent invitation has a new link. |
| **This invitation was sent to a different email address.** | Sign in with the email address that got the invitation. On the join page, click **Switch account**. |
| The invitation link says it was withdrawn or already accepted. | Ask the team for a new invitation if you still need access. |
| **Reassign members off this role before deleting it.** | Change the access of each member who holds the custom role, then delete it. |
| **Could not save the selected team. Allow browser storage and try again.** | Your browser blocks site storage. Allow storage for the console, then switch teams again. |
| **Archive team** is disabled. | Fix each failed check in the dialog first, such as terminating servers or paying invoices. See [Archive the team](/team/settings#archive-the-team). |

## Billing

| Problem | Fix |
| --- | --- |
| **Add your billing details** banner. | Click **Add billing details** and enter your currency, legal name, and address. You need them to add credit, add a payment method, and create servers. |
| **Add a payment method to create servers.** | Your credit does not cover the server and the team has no payment method. [Add a card](/billing/payment-methods#add-a-card) or [add credit](/billing/limits#add-credit). |
| **Your trust tier limit is reached.** | Your team runs the most servers your tier allows. Terminate a server you no longer need, or contact support to review your tier. |
| **This plan and your pending server requests exceed your spending limit.** | Choose a smaller plan, or contact support to review your limit. See [Credits and spend limits](/billing/limits). |
| A red or amber banner says an amount is overdue or outstanding. | Click **Pay now** and pay the invoice. See [Pay an outstanding invoice](/billing/invoices#pay-an-outstanding-invoice). |
| A payment attempt failed. | Add another card or move a working card to the top, then pay the invoice. |
| **Action required: choose how to keep paying.** | Your wallet does not cover an INR bill, and the remaining amount is more than ₹15,000. Your card or UPI cannot pay that amount automatically. Or your UPI Autopay or card mandate was revoked or failed. Click **Choose how to pay**. Select **Pay each invoice** or **Prepaid wallet**, then click **Confirm**. With **Prepaid wallet**, add credit to cover the bill. Your card or UPI pays only amounts up to ₹15,000. |
| The invoice download icon is disabled. | The invoice is not issued yet. The PDF is ready after the invoice is issued. |
| **Primary payment method** is disabled. | Your wallet has a balance, so credits pay first. The option is available when the balance is zero. |

## Servers

These messages show when a server action does not complete.

| Message | Fix |
| --- | --- |
| **You don't have access** | Ask a team Admin to give you server access, or switch to a team where you have it. |
| **This region is temporarily unavailable** | Try again in a few minutes. If the problem continues, contact support. |
| **No room for this size** | Choose a smaller size, or try again later. |
| **The server wasn't created** | Try again, or select another region if the problem continues. |
| **The [action] is taking too long** | Refresh the server list in a few minutes. If it still looks stuck, contact support. |
| **We're still confirming this request** | Frappe Cloud keeps checking. Do not submit the request again. |
| **The [action] didn't complete** | The server is in a failed state. Contact support before you submit another action. |
| **Setup needs support** | Do not submit another request. Contact support with the action ID. |
| **The final snapshot didn't complete** | The server is stopped and was not removed. Start it again, or terminate it without a snapshot. |
| **Server not found** | The server was terminated or belongs to another team. Refresh the server list. |

## Contact support

Open **Get help** from your name at the bottom of the sidebar, then **Help > Contact support**. Some messages in the console also have a **Contact support** link, and each server menu has one. The dialog opens with the server or site that you asked from.

**Get help** looks for an answer before it asks you to write a ticket. When the support desk has no help articles yet, the dialog opens on the contact stage.

1. Describe the problem in your own words. Help articles and your team's past tickets appear as you type. Each row opens in a new tab.
2. Read the rows. When an answer matches, the button reads **Still need help?**. The answers come first, so the dialog does not offer a ticket until you say the answers do not help.
3. When no answer matches, the button reads **Contact support**. It is enabled after 3 characters and after the search completes.

The contact stage shows **Topic** and **Issue**. It fills the description with your question. If you opened the dialog from a server, select the server and its site. The line below the details shows the email address that support will see. Click **Send to support**.

If a server or site is down, click **Report an outage** instead of searching. The contact stage opens with the urgent issue selected, so support sees the ticket first.

To see your team's open tickets, click **Your tickets** in the dialog header. The list shows the tickets that support has not resolved. Click the external link on a row to open the ticket in the support portal. A ticket that a teammate raised shows their email address and has no link, because only that person can open it in the portal. If the portal asks you to sign in, use the same email address that you use for Frappe Cloud. Click **Back** to return to the search.

When Central has a support portal link but no ticket connection, **Contact support** opens the support portal in a new tab instead.

## See also

- [Members and invitations](/team/members)
- [Payment methods](/billing/payment-methods)
- [Invoices](/billing/invoices)
- [Resize, stop, and terminate](/servers/lifecycle)
