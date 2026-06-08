# 03 — Authentication & SSO

This is the spine of v1. Two distinct problems:

1. **Login** — how a user authenticates *to Central*.
2. **SSO hand-off** — how a logged-in Central user is *seamlessly logged into an
   Atlas cluster* when they select an asset.

## 1. Login to Central

Use Frappe's native auth — nothing custom.

- **Email + password** (Frappe built-in).
- **Social login** (Google / GitHub) via Frappe **Social Login Key** — framework
  supported, zero custom code.
- Optional TOTP via Frappe's built-in 2FA (future toggle).

The SPA at `/dashboard` is gated server-side, mirroring Atlas's
`www/dashboard.py`: if `frappe.session.user == "Guest"`, redirect to
`/login?redirect-to=/dashboard`. On success the page injects `csrf_token`,
`user`, and `site_name` into the boot payload for the SPA.

## 2. SSO hand-off into Atlas — Central is an OAuth2 *provider*

**Decision: use Frappe's built-in OAuth2 provider** (`frappe.integrations.oauth2`).
Central is the identity provider (IdP); **each Atlas cluster is an OAuth2 client**
configured as a Frappe **Social Login Key** pointing at Central. This is the
"SSO supported in the framework" path — no hand-rolled JWT, no custom crypto, and
it reuses the exact mechanism Frappe already ships for "Login with Frappe Cloud".

### One-time setup (W1, per cluster)
1. In Central, create an **OAuth Client** (Frappe DocType) for the cluster:
   redirect URI = `{base_url}/api/method/frappe.integrations.oauth2_logins.login_via_<provider>`
   (the standard Frappe Social Login callback), scopes = `openid` (+ `all`/profile
   as needed). Central issues `client_id` / `client_secret`.
2. Store `client_id` on the Central `Cluster` row; hand `client_id` + `client_secret`
   to the cluster operator.
3. On **Atlas**, add a **Social Login Key** named e.g. `frappe-cloud` with
   Central's base URL as the provider, the issued credentials, and
   `OpenID`/`OAuth2` endpoints pointing at Central
   (`/api/method/frappe.integrations.oauth2.authorize`,
   `/api/method/frappe.integrations.oauth2.get_token`,
   `/api/method/frappe.integrations.oauth2.openid_profile`).
   **This is new work on Atlas** (Atlas has no SSO today) — tracked in `OPEN-QUESTIONS`.

### The runtime flow (W3)

```
User is signed into Central (session cookie on cloud.frappe.io).
Clicks "Open" on vm-42 (cluster = bangalore) in the registry list.

 1. Central SPA computes the cluster deep link and navigates:
      window.location.href =
        https://bangalore.x.frappe.dev/dashboard/machines/<vm_id>

 2. Atlas www/dashboard.py sees Guest → redirect
      /login?redirect-to=/dashboard/machines/<vm_id>

 3. Atlas login page shows "Login with Frappe Cloud" (the Social Login Key).
    User clicks (or Atlas auto-initiates it). Browser →
      https://cloud.frappe.io/api/method/frappe.integrations.oauth2.authorize
        ?client_id=<cluster>&redirect_uri=...&response_type=code&scope=openid&state=...

 4. Central: user ALREADY has a session → no re-login. Central authorizes
    (first time may show a one-time consent), issues an auth code, redirects to
    the cluster callback with ?code=...&state=...

 5. Atlas exchanges code → token at Central's token endpoint, calls
    openid_profile to get the user's email/identity, finds-or-creates a local
    Atlas User, and creates a native Frappe session (its own cookie).

 6. Atlas honours redirect-to → lands the user on /dashboard/machines/<vm_id>,
    fully signed in. No password re-entry.
```

The visible URL change to `bangalore.x.frappe.dev` **is** the hand-off; the SSO
makes it frictionless. After step 5, Central is out of the request path entirely.

### Why OAuth2 and not a custom signed token?

| | OAuth2 provider (chosen) | Signed-token + `login_as` (fallback) |
|---|---|---|
| Framework support | Built-in both ends (provider + Social Login) | Custom endpoint on Atlas |
| Crypto to maintain | None (framework) | You own JWT signing/rotation |
| Consent / scopes | Built-in | Hand-rolled |
| Revocation | Token revocation built-in | Manual |
| Effort on Atlas | A Social Login Key (config) | A new `/auth/handoff` route + `login_as` |

The signed-token fallback (Central mints a short-lived JWT scoped to one cluster;
Atlas verifies against a shared secret and calls
`frappe.local.login_manager.login_as(user)`) is documented as a backup if the
OAuth2 route proves awkward, but **OAuth2 is the v1 design.**

## Permissions ride in the token (see `spec/06`)

The OIDC token is not just identity — it is also **how permissions reach Atlas**.
At authorize/userinfo time Central adds an `fc_teams` claim: a bounded map of the
user's `team → role + capabilities`. Atlas enforces VM actions from this claim,
in-session, never calling Central per request. This is deliberate: we reuse the
token we already issue rather than building a separate permission-sync channel.
Staleness is bounded by the token lifetime; a Central outage lets existing
sessions run to expiry while new logins fail. Full model in `spec/06`.

## Deep-link preservation (required Atlas fix)

For the hand-off to land on the *exact* asset (not a generic dashboard), Atlas's
`www/dashboard.py` must echo the requested path through login instead of
hardcoding it:

```python
# Atlas — preserve the full requested path (incl. the /t/<team>/ segment, spec/06)
frappe.local.flags.redirect_location = f"/login?redirect-to={frappe.request.path}"
```

This is the one concrete change Atlas needs for a true deep-link hand-off
(tracked in `OPEN-QUESTIONS`).

## Security rules

- **Per-cluster client credentials.** One OAuth client per cluster; compromise of
  one cluster's secret never grants access to another.
- **Tokens/codes are short-lived** (framework defaults) and **cluster-scoped** via
  `client_id` + `redirect_uri` allow-list.
- **Account state is global.** Disabling a User (or changing a role) in Central
  propagates via the **token lifetime**: the next token refresh reflects it, and
  new authorizations are refused immediately. An already-issued token works until
  it expires — the deliberate, simple bound (`spec/06`). Instant cross-cluster
  termination remains an `OPEN-QUESTION` only if a tighter bound is ever needed.
- **W2/W4 service calls** use the per-cluster Atlas **API key/secret** (stored as a
  `Password` field), never a user token.
