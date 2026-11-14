# Central certificate expiring

The certificate of Central expires in less than 14 days, or the handshake fails. The alert detail shows the days left or the error.

1. Open the Central URL in a browser and read the certificate: its expiry and the names that it covers.
2. If renewal failed, read the renewal log of the Central host and fix the cause, such as DNS or a rate limit. Then renew the certificate.
3. If the certificate does not verify, check that the host serves the full chain for the Central name.
