# Central API errors

The Central API or dashboard returns 5xx for many requests. Customers cannot sign in, create sites or manage servers. The alert key names `all` (10 minutes, pages), `hourly` (1 hour) or `group:<group>`, the API module that fails.

1. Open the Error Log list in Central, newest first. The Beacon alert `central-errors` names the error that repeats.
2. For `group:oidc`, `group:sso` or `group:auth`, check sign-in: Central SSO settings, the JWKS endpoint and the identity provider.
3. For `group:sites` or `group:servers`, check the regional services that Central calls. A failed region makes these calls fail.
4. When the errors started after a deploy, roll back the deploy.
5. Post an update when customers see errors.
