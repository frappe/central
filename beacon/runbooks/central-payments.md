# Central payments failing

Customers pay through a payment gateway. The alert key names the check and the gateway.

- `attempts:<gateway>` (High): 5 or more payments failed in 1 hour, and they are half of the attempts.
- `webhooks-waiting:<gateway>` (High): a gateway webhook waits for more than 15 minutes. The money arrived, but Central did not apply the credit.
- `webhooks-failed:<gateway>` (Medium): Central could not process a webhook in the last hour.
- `no-capture:<gateway>` (Low): no payment was captured for 1 day.

1. Open the Payment Attempt list in Central. Filter by the gateway and the Failed status. Read **Gateway Response**.
2. Open the status page of the gateway. When the gateway has an outage, wait and post an update for customers.
3. For waiting or failed webhooks, open the Webhook Event list. Read **Error**. Fix the cause, then process the event again.
4. When many payments fail with the same error after a change in Central, roll back the change.
