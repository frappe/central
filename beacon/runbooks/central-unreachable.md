# Central unreachable

Beacon cannot load the Central dashboard or call the Central API from outside for 3 minutes. The alert names the URL, and its detail shows the error or the status. Customers cannot sign in, manage their sites or pay.

1. Open the URL in a browser. If DNS or TLS fails, check the DNS record, the load balancer and the certificate of Central.
2. If the request times out or returns 502, check that the web workers and nginx of the Central site run. Restart the bench processes if they do not.
3. If the API returns 5xx, follow the Central API errors runbook.
4. Post an update on the incident and on the status page, because every customer is affected.
