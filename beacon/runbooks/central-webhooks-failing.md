# Central webhooks failing

Central sends events to other services with Frappe webhooks, for example the VM state of a site to its region. Frappe retries a failed request. After the last retry, the request is **Exhausted**, and the receiver never gets the event. The alert key is the name of the webhook.

- High: 10 or more requests of one webhook are Exhausted in 1 day, and they are 20% of its requests.
- Medium: 1 request is Exhausted, or 10 requests wait for a retry.

1. Open the Webhook Request Log list in Central. Filter by the webhook and the Exhausted status. Read **Error** and **Response**.
2. When the receiver is down or rejects the token, fix the receiver first. Then open each Exhausted log and send it again.
3. When the error is in Central, for example a bad payload, fix it and deploy. Then send the Exhausted logs again.
4. When the webhook is no longer used, disable it. Frappe then marks its waiting requests Exhausted, and the alert resolves after 1 day.
