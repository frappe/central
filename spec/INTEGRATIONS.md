# Integrations with Atlas, Pilot, and Cargo

## Purpose

Central owns identity, Team capabilities, catalog policy, and billing. Atlas owns regional images, virtual machines, placement, and proxy routing. Pilot owns the benches and sites inside a server. Cargo builds the prepared images.

Central reaches each service through `central/integrations/`. Team authorization follows [IAM](IAM.md) and [Capabilities](../CAPABILITIES.md).

The planned abuse protection calls to Atlas, the proxy, and Cargo are in [Abuse protection](ABUSE.md#interfaces). Planned: Atlas also sends a `vm.network` event to Central when the network state of a VM changes. See [Events from Atlas](ABUSE.md#events-from-atlas).

Planned: `central/integrations/cargo.py` calls `attribute_address` to find the VM behind a shared NAT address, with an `atlas-cargo:<region>` token of scope `abuse:attribute`. See [Calls to Cargo](ABUSE.md#calls-to-cargo).

## Who owns what?

```text
Customer -> Central Team -> trial VM -> Pilot site
                |
Central: permissions, product choice, operation record, domain claim
                |
                +-> Atlas: VM creation, placement, power, sleep, host migration
                +-> Regional proxy: applied hostname routes
                +-> Pilot: site/admin rename, site configuration, certificates
                +-> Cargo: regional storage lifecycle and bucket operations

Atlas/Cargo report -> central.api.state_delivery.receive -> scoped state update
Central repair scan -> same state update
```

Central does not issue certificates, edit guest nginx, transfer VM disks, or select Metal hosts. All remote calls stay under `central/integrations/`.

Central owns authorization and the customer-visible result. It verifies that a requested domain belongs to the caller before it changes a regional route.

The customer Team owns the trial before and after a paid upgrade. A Team can own several VMs with the same network tenant ID.

## Regional authentication

Region stores the direct regional URL and numeric region ID, alongside its geography and display identity. Central signs a short-lived token for that region. Each request carries the Team tenant ID in `X-Tenant-ID`. Atlas verifies the token and enforces the tenant boundary. Each request also carries the Central trace ID in `X-Frappe-Request-Id`. Atlas uses it as its own trace ID, so a Central Error Log and the Atlas logs of the same work share one ID. Both need `monitor` on in the site config.

System images form a shared regional catalog. The tenant header identifies the authorized caller. It does not make those images Team-owned. Operator connection checks use the system tenant.

See [Regional configuration](../central/infrastructure/doctype/region/SPEC.md) for trust setup and connection checks.

## How are tenants and regional keys managed?

Allocate unique, immutable, unsigned 32-bit Team tenant IDs through a persistent sequence. Reserve tenant zero for infrastructure. Preserve verified existing mappings and reject ambiguous data.

Do not reuse committed tenant IDs. Backfill before you enforce constraints. Test concurrent allocation and the actual migration order.

Store regional VM references with their Region. A VM name alone is not globally unique. Do not change existing Central resource IDs without need.

Central owns image offering presentation and matching tags. Central fetches regional System image builds from Atlas on demand. See [Image offerings](../central/infrastructure/doctype/image_offering/SPEC.md).

The Atlas image response exposes tags, architecture, availability, and disk size. Declare and test software resource requirements at the image builder. Do not duplicate regional builds or copy runtime metadata into Central by hand.

A matching size permits a warm start but does not guarantee that the selected host has the warm artifact. Cold startup must stay usable.

Regional tokens use Ed25519 keys with a `central:` key identifier. Atlas tokens carry `iss=central`, `aud=atlas-admin:<region ID>`, `scope=*`, and `tenant=*`. See [SSO](SSO.md) for every token type.

The client supplies `X-Tenant-ID` from the authorized Team. Never accept a customer-supplied tenant header as authority.

Publish keys before use and verify consumer acceptance. Serialize first-use key creation. Restrict key changes to operators.

A public key-set read must not rotate keys. Keep private keys and bootstrap credentials out of customer responses.

Region is the single owner of regional identity and connection configuration.

## Image contract

Central fetches available System images when the customer selects a region and Image Offering. An offering contains presentation fields, allowed flows, and required tags. It does not store regional builds.

Atlas must return the following fields with each build:

| Field | Central use |
|---|---|
| ID, title, tags, and architecture | Identify and describe the selected build. |
| Enabled flag and availability state | Show only usable builds. |
| Root filesystem size in MiB | Reject plans whose disk cannot hold the image. |

Cargo's current Pilot image contains `default-bench` and `site.local`. Server and signup flows use that image layout. Ubuntu uses a base image. SSH keys are optional. See [Image Offering](../central/infrastructure/doctype/image_offering/SPEC.md) for selectors and pagination.

Server creation has three network options. Central sends an option to Atlas only when the customer selects it:

| Option | Atlas create field |
| --- | --- |
| Public IPv4 | `public_ipv4: "auto"`. Refused when the region has no IPv4 price. |
| Public IPv6 | `public_ipv6: "auto"` |
| Firewall | `firewall.enabled: true` with the rules below |

Each option has a flag in Central Settings > Feature Flags > Networking: Enable Public IPv4, Enable Public IPv6, and Enable Firewall. Each flag is off by default. When a flag is off, the New server page hides that option, and Central refuses a creation request that selects it.

Every creation also sends the disk IOPS, disk throughput, and private and public network throughput from Central Settings > Servers > Server Limits. A change applies to servers created after it.

Every new server gets the web server rules: inbound TCP ports 22, 80, and 443 and all outbound traffic, after the system rules in [Firewall](#firewall). The option only sets `firewall.enabled`. A disabled firewall permits all traffic and keeps the rules for when the customer turns it on.

A creation request can carry `user_data` of up to 16 KiB, which is also the Atlas limit. Central sends it to Atlas unchanged as `guest.user_data`, and cloud-init in the guest runs it on first boot. A caller uses it to set up a server without signing in after creation. Central saves it on the Resource Action with the other creation inputs, so it must not hold a long-lived secret.

Atlas reports the guest public IPv6 as a `/128` prefix. Central stores the address without the prefix length in `public_ipv6`, and stores `public_ipv4` as reported. See [Public addresses](#public-addresses) for changes after creation. The overview shows `ssh root@<address>` for every image and uses the IPv6 address first. See [Team SSH Key](../central/infrastructure/doctype/team_ssh_key/SPEC.md) for selected keys and rotation.

A member with `server:console` can open the web console of a running server of any image. In the server actions, Web console opens a submenu with two modes. Central sends the selected mode to Atlas through `POST /virtual-machines/{id}/actions/console-token`.

| Mode | Session | Password |
| --- | --- | --- |
| `ssh` | A new shell as `root`. Atlas adds a temporary key for the session and removes it when the session ends. The guest SSH service must run. | Not necessary. |
| `tty` | The shared serial console. It replays recent boot output and stays open across a restart. Use it when SSH does not respond. | Necessary. The guest shows a login prompt. |

`open_console(team, resource_id, mode)` accepts only `ssh` or `tty`. Central does not change the mode. If Atlas refuses an `ssh` token, the member sees a message that tells them to open the serial console. Central returns `<region base URL>/vm_console#token=<token>`. The dashboard asks for a new token each time a member opens the console from the overview or the server actions, because Atlas spends the token on first use. It opens the Atlas URL in one popup window per server, so a second request replaces the session in that window. The token expires after 30 seconds and stays in the URL fragment, so the browser does not send it to a server.

## Firewall

The Networking tab of a server shows its firewall. A member with `server:network` can change it.

| Change | What Central sends | Confirmation |
| --- | --- | --- |
| Turn the firewall on or off | `enabled`, plus default rules when enabling an empty firewall | When it opens every port, or blocks SSH or all outbound traffic |
| Apply changes | `inbound` and `outbound` only | When the saved rules block SSH or all outbound traffic on an enabled firewall |
| Copy to other servers | `enabled`, `inbound`, and `outbound` | None. The dialog names the servers. |

Rule edits stay in the browser until the customer selects Apply changes. Each direction is a table with the columns Service, Port and Allowed from or Allowed to. Removing a rule takes it out of the table at once. Undo, or Cmd+Z on macOS and Ctrl+Z elsewhere, restores the draft one step at a time. Quick edits to one rule count as one step. In a text field and in a dialog, the shortcut keeps its normal text behavior. A footer below the rules always shows the number of unsaved changes or the reason Apply changes is blocked, with Undo, Discard and Apply changes. Discard restores the saved lists. An unchanged background observation does not replace a pending draft. If the saved rules change, Apply changes is blocked until the customer discards the draft to load the latest saved rules. The presets Web server, SSH only, and Private only fill the rule lists for review before applying. Enabling a firewall with no saved rules allows SSH, HTTP, HTTPS and all outgoing connections.

Each row selects a service and either Anyone on the internet or Specific addresses. Anyone permits both IPv4 and IPv6. Specific addresses shows each address of the rule as a removable chip, and an input for another IP address or canonical CIDR range. Enter or Add adds it to the rule. The input suggests addresses that other rules in the same direction use. A single IP becomes a one-address range. Incomplete rules show guidance and cannot be applied. Invalid entries show a field error. An empty TCP or UDP port means all ports for that protocol. Custom ports stay editable when their value matches a preset service port. Central validates the complete change before sending it to Atlas.

`update_server_firewall` takes a list of servers and returns an error or `null` for each one. Central validates the change first: protocol `any`, `tcp`, `udp`, or `icmp`; ports only for TCP and UDP, as one port or one ascending range; address ranges in canonical CIDR form; and each rule only once.

Central sends the change through `PATCH /virtual-machines/{id}/network`. Atlas replaces each firewall field it gets and keeps the others. Central puts these system rules before the customer's inbound rules, and the dashboard does not show them.

| Rule | Why |
| --- | --- |
| All traffic from `fdaa::/16` | The console and the regional gateway reach a machine over the mesh, and an enabled firewall filters mesh traffic too. |
| All traffic from `fdac::/16` | WireGuard gateway clients. Atlas still drops them unless the VM opts in to gateway access. |
| ICMP from anywhere | IPv6 neighbour discovery and path MTU need it. |

Atlas checks at most 50 address ranges across all rules, system rules included. The PATCH reply does not hold the firewall, so Central reads the VM again. Every read stores `is_firewall_enabled` and the customer's rules in `firewall_rules`. A server that Central has not read since this field was added shows its firewall after the next reconcile, which runs every 10 minutes.

## Public addresses

A member with `server:network` on a server can attach or detach its public IPv4 and IPv6 addresses, and turn IPv4 internet access on or off, from the Networking tab.

| Operation | Atlas request | Notes |
| --- | --- | --- |
| Attach | `PUT /virtual-machines/{id}/public-ipv{4,6}` with `{"public_ip": "auto"}` | Atlas picks an address from the region's pool. For IPv4, Central first turns on IPv4 internet access, because Atlas requires it. |
| Detach | `DELETE /virtual-machines/{id}/public-ipv{4,6}` | The address goes back to the pool. The customer cannot get it back. |
| IPv4 internet access | `PATCH /virtual-machines/{id}/network` with `ipv4_internet_access` | Stays on while the server has a public IPv4. |

Atlas applies an attach or detach after it replies. Central waits up to 30 seconds for Atlas to report the change, then reads the server. A slower change appears on the next reconcile. Central does not use reserved addresses yet, so an address always belongs to one server.

A public IPv4 is billed from the first read that reports it until a read no longer reports it, or the server is terminated. `VirtualMachine.sync_public_ipv4_billing` opens and closes one `Subscription` per server, linked by `public_ip_server`. The price is the Catalog Rate of the `IP` Resource Type for the team's currency, optionally per region. The starter rates are INR 170 and USD 2 per month. Central refuses to attach an IPv4, or to create a server with one, in a region without a rate. IPv6 is free.

## Termination protection

A member with `server:terminate` can turn termination protection on or off with the lock button in the server header. Central sends `PATCH /virtual-machines/{id}/termination-protection` and stores the `is_termination_protected` value that Atlas returns on the Virtual Machine. Atlas does not report this value in a VM read, so the stored value changes only through this request. Central refuses a terminate request for a protected server before it queues a Resource Action, and Atlas also refuses to delete a protected VM.

## Server operation contract

Central stores each authorized operation in Resource Action before dispatch. Atlas receives one create or power request. Central saves the accepted VM identity before local finalization. A lost mutation response remains uncertain and must not trigger another remote mutation.

Scoped regional reads confirm VM state and repair interrupted local finalization. A failed read does not prove deletion. A scoped not-found response can confirm deletion and trigger local credential and billing cleanup.

Central builds the automatic management address itself. The regional proxy decodes a VM's mesh address from its hostname label, so Central encodes the same label from the observed mesh address and the region's proxy domain. The tenant API does not publish the regional zone, so an operator sets `proxy_domain` on [Region](../central/infrastructure/doctype/region/SPEC.md). A management address alone does not prove Pilot readiness. Pilot creation also receives credential-bound `pilot-central` metadata and `pilot-common-config` metadata with the telemetry settings when the region has a telemetry host. When Central Settings has a **Common Site Config**, every server also gets it as `pilot-common-site-config`, which Pilot merges into `sites/common_site_config.json` at bootstrap, such as an app's relay URL. The customer can read it, so it holds nothing Central keeps from them (a trial's Grove key is the customer's own credential). Every Pilot server's `pilot-common-site-config` also holds `fc_team`, the server's Team, so Frappe's Pulse telemetry on each site files its events under that Team. When the region links an enabled **FrappeMail Service**, Central takes a ready mailbox from that service's pool, records it as a **User Mail Account** for the creation, and adds its SMTP settings to `pilot-common-site-config`: the SMTP server on port 587 with STARTTLS, the mailbox as login and sender, and `always_use_account_email_id_as_sender`. Pilot and every site then send mail through it. The password belongs to that one server. An empty pool fails the creation. A job every 5 minutes fills the pool to the service's minimum with send-only mailboxes, named `notifications-<hash>@<domain>`, through the Suite site's admin API. It adds at most 50 in one run. Central removes a server's mailbox from the Suite site when the server is terminated. Atlas refuses guest metadata with more than 16 entries or more than 48 KiB as compact JSON, and the region's host refuses a key longer than 128 bytes. `AtlasClient.create_vm` refuses the same metadata before it calls Atlas, because Atlas saves a draft machine before the host rejects a key.

Pilot creation includes the requesting user's email as `letsencrypt.email` in `pilot-common-config`. Pilot saves it in `common_config.toml` for certificate requests. Central reads the user from `Resource Action.requested_by`, not from the dispatch worker session. This setting is sent even when telemetry is unavailable. A request with no user email leaves the setting unset. This applies to new VMs; existing VMs keep their current setting.

A free-trial creation also gets a Grove key when AI Settings keeps a pool of them (**Trial Pool Size** above 0). Central mints the pool ahead, every 5 minutes, under the fixed Grove Team `Central Trial`, which an operator makes at Grove first, in the geography and Model Group AI Settings name (blank: that geography's default group), each key capped for its life at **Trial Key Cap** and carrying no expiry of its own: its life is its trial's. Each key is an **AI Trial Key** record that holds the secret. The creation takes the oldest ready key, records the creation on it, and adds it to `pilot-common-site-config` as `ai_keys`: the key's gateway URL and secret, the entry Pilot writes for a team's own keys. A paid creation gets no key. An empty pool does not fail the creation: the trial starts without AI. Central revokes the key at Grove when the creation fails, when the trial ends and when the server is terminated, and tries a refused revoke again every hour. When the trial converts, Central hands the key to the team at Grove in the background: the same secret, now the team's, titled by the site, in the geography's default group and without the trial's expiry, so the server's config keeps working and the team finds the key in its dashboard (AI is turned on for the team first; every conversion path has a payment method). The record goes Converting, then Converted. A hand-over Grove refuses or cannot hear is tried again every hour and given up after three attempts as Conversion Failed, said on the record and the Site with Grove's last answer (the record's **Last Error**, kept from any failed hand-over or revoke until one lands); the key is then revoked like any trial key's (the record's **Revoked** box ticks once Grove has it; its status keeps the failure) and the team creates its own key. An operator's **Extend Trial** of an ended trial starts it without an AI key, which its end revoked; the Site says so. The gateway closes the key's books at the push that moves it, so what the trial spent stays Central Trial's and what follows is the team's.

See [Resource Action](../central/infrastructure/doctype/resource_action/SPEC.md) for states, authorization, recovery, accepted quotes, and customer responses.

## How does a site prove its team to an outside service?

An app on a site, such as Raven, asks Central for a token through Pilot's Central proxy: `central.api.pilot.get_team_identity_token(audience)`. Pilot's credential names the team, so a site cannot get a token for another team.

`get_team_identity_token` returns a token that Central signs with its Pilot key. The token is valid for 5 minutes. Central stores no account and no secret for the outside service.

| Claim | Value |
|---|---|
| `iss` | Central's issuer URL |
| `aud` | The service URL that the site gave as `audience` |
| `sub` | The team, such as `TEAM-00042` |
| `team_name` | The team's name |
| `scope` | `team-identity` |
| `hosts` | The hostnames of the team's sites on the Pilot's server: each site's own address and its active Site Domain records. Empty when the credential has no server. |

The service gets Central's public keys from `central.api.jwks.get_jwks` and verifies the signature, `iss`, `aud`, `exp` and `scope`. Then the service decides what access the team gets, for example a team account and its API keys. The Pilot credential names the team and its server, so a site cannot get a token for another team or for a hostname that the team does not serve. A service uses `hosts` to accept a site's hostname as the team's. A Pilot refuses a `team-identity` token as a login token.

## How does a Pilot read private GitHub repositories?

Central owns the GitHub App, set on the GitHub tab of Central Settings. The App private key and secrets stay in Central. A Pilot gets only a token for one repository, with `contents: read`, that expires in about an hour.

```text
Pilot ── start_connection ──> Central ── authorize, install ──> GitHub
  ^                             │ user with server:console picks repositories
  └──── repository_token ───────┘ GitHub Connection (grant)
```

1. Pilot calls `central.api.integrations.github.start_connection(return_url)` with its credential and gets a link to `/dashboard/github/connect/<attempt>`. The attempt lives in Redis for 1 hour after the last activity. The `return_url` lives 24 hours, so an expired link still leads back to the server.
2. The first user who opens the link must hold `server:console` on the Pilot's server. The attempt binds to that user. The OAuth `state` and a PKCE verifier bind the GitHub callback to the attempt and the user's session.
3. The user authorizes or installs the App, then selects repositories in one or more accounts. The user must be a GitHub admin of each one. `complete_connection` saves one `GitHub Connection` per Pilot credential and installation. An account sent with no repositories loses its grant.
4. Pilot calls `status`, `repositories` and `repository_token(repository)` with its credential. Each grant change increases the connection `version`. Central refuses a token when the grant changed while GitHub minted it.
5. The signed GitHub webhook disables a connection when its installation is deleted or suspended, removes repositories the installation lost, and updates the name of a renamed repository. The App must subscribe to the `repository` event for renames. `disconnect` disables the Pilot's grants. Issued tokens stay valid until they expire.

The App needs one callback URL, on Central's issuer URL (`central_url()`). "Create GitHub App" in Central Settings creates the App from a manifest and fills the GitHub tab. A new App ID disables every grant, so each Pilot must connect GitHub again.

## How does the trial flow work?

1. Authenticate the customer and resolve the Team.
2. Validate the trial limit, approved image, size, region, and existing eligibility.
3. Persist the request and its unique customer request key.
4. Issue and store a VM-specific Pilot credential and audience.
5. Call Atlas with the image, size, sleep policy, and `pilot-central` metadata.
6. Store the returned VM reference and automatic site and admin names.
7. Observe the VM and verify bounded Pilot and site readiness.
8. Record the site already present in the prepared image.
9. Return the site login through the dashboard.

Metadata contains `central_endpoint`, `central_auth_token`, `jwks_url`, `jwks_audience_id`, and `initial_jwks_cache`. Do not put customer credentials into the shared image.

A VM running event can finish VM provisioning. It cannot prove that the site is ready for login. Keep VM state and site readiness separate.

Persist the request before remote work and enqueue after commit. A recovery sweep finds requests lost between commit and enqueue.

Central request deduplication does not make Atlas creation safe to repeat after a network timeout. Keep uncertain acceptance as an explicit state. Resolve an uncertain create through a verified lookup or operator recovery. Do not send a second create automatically without an upstream idempotency contract.

Bind credentials to the known VM. Revoke unused credentials after confirmed provisioning failure and bound credentials after confirmed deletion.

Do not disable eligibility, Team authorization, size validation, or trial-abuse checks.

## How do server creation and lifecycle work?

Trial, Pilot-server, and plain-Ubuntu creation use the same authorized Atlas adapter. Each flow has an explicit readiness rule.

| Resource | Configuration | Completion |
|---|---|---|
| Trial | Prepared Pilot image, one existing site, metadata credential, approved idle timeout. | VM accepted, Pilot ready, site reachable, and site login succeeds. |
| Pilot server | Cargo Pilot image with its prepared bench and site, plus metadata credential. | VM is ready and Central can open the correct Pilot admin. |
| Plain Ubuntu | Approved Ubuntu image, allowed size, hostname, and SSH keys. | Atlas confirms the requested running state and the agreed access configuration. No Pilot or Site record is required. |

Show Open Pilot only for a Pilot-managed resource. A plain Ubuntu VM must not fail because it has no Pilot process or site.

Do not expose privileged VM creation or system tenant zero to customers.

Idle sleep is a trial policy. Ordinary Pilot servers and plain Ubuntu servers have no idle sleep unless their product requires it.

Record each operation separately from observed state and show a useful error on failure.

An explicit stop sets the desired state to stopped. It is different from idle sleep, where desired state stays running. Customer traffic must not undo an explicit stop.

A restart completes when the region accepts it and Central then reads the server as Running. The host stores the restart before Atlas replies, and the region never reports a state other than running during a restart. A failed restart shows as an error on the server, which Central records as Failed.

Opening Pilot uses a short-lived audience-bound token and the automatic admin name. Deny another Team's access.

A System Manager has three more actions on the Virtual Machine form in Desk. Central records the first two as a Comment on the server.

| Action | Effect |
| --- | --- |
| **Open Bench as Administrator** | Opens the bench with the same one-click token, for a Running server with a gateway. |
| **Revoke Pilot Access** | Revokes every Pilot Credential of the server, so its Pilot can no longer reach Central. |
| **Retry Admin Domain** | Asks Pilot again for the admin hostname, when the server shows an admin domain error. |

Pilot links back to its server in the console with `/dashboard/servers?pilot=<jwks_audience_id>&action=<action>`. The action is `overview` or `resize`; any other value opens the overview. A resize link opens the dialog only when the server can take a change and the user may resize it. The server list returns each server's active audience as `pilot_audience`, and the console matches the link against it. When the active Team does not hold that server, the console shows the server list and a message. On a fresh page, the link waits for the first server list load before it looks for the server.

Display supported network and SSH information for a plain Ubuntu server. Do not imply that a private mesh address is publicly reachable.

Delete only after the customer confirms the action. Confirm remote absence, revoke any Pilot credential, and preserve existing billing cancellation behavior.

## What does creation depend on?

The current creation flow requires the Atlas VM API and automatic management hostname. Staging also needs current schema, key trust, a healthy host, available images, and wildcard DNS.

Central receives signed state reports at `central.api.state_delivery.receive`. See [Inbound webhooks](WEBHOOKS.md) for the contract. State reports supplement repair reads. They do not replace durable intent, and a callback is never the only recovery path. Resize uses the Atlas resize API, which moves a VM to another host when its host cannot fit the new size. When no host in the region can fit the new size, Atlas keeps the old size. Central then starts the server again if it was running, and fails the resize with `REGION_AT_CAPACITY`. Atlas does not stop a sleeping VM, so a CPU or memory resize starts a sleeping server first.

Central verifies domain ownership and owns the proxy route through [Site Domain](../central/infrastructure/doctype/site_domain/SPEC.md). The regional proxy terminates TLS for a regional name. For a custom domain, the proxy passes TLS to the VM, and Pilot holds the certificate. Central does not issue or store certificates.

## How does state delivery work?

Atlas uses Framework's Webhook DocType to send reports. Do not rebuild an Atlas event service or a generic message platform.

Atlas and Cargo both deliver to `central.api.state_delivery.receive`. `X-FC-Source` selects the handler. [Inbound webhooks](WEBHOOKS.md) is the contract.

### Atlas sender

Configure a Webhook on Virtual Machine State with `on_update`. Verify that it covers insertion and later saves in the deployed Framework revision.

The payload carries the event, the VM ID, the observed status, and `observed_at`. Do not serialize an entire document.

The state writer saves on each host report, even when the status is unchanged. Use a tested condition for first observation or status change to avoid continuous duplicate callbacks. Do not assume that editing a Webhook filters unchanged values.

The state row has no tenant, desired state, operation ID, or site readiness. Central resolves the Team through its stored Region and VM mapping.

A callback can arrive before Central stores the create response. Central drops it as `unknown server`, and a repair read records the state later. Do not create a Team or resource from untrusted callback fields. The callback must not assign a machine to a customer based on its name.

### Verification and ordering

Central verifies `X-Frappe-Webhook-Signature` with base64 HMAC-SHA256 over the exact raw request body. Each region has its own secret for each sender. A region identifier selects a candidate secret. It becomes trusted only after signature verification.

Central validates the source, fields, status, and resource mapping. It rejects unknown senders and bad signatures uniformly.

Central orders Atlas reports by the region's `observed_at`, stored as `Virtual Machine.last_reported_at`. It ignores a report that is not newer. A signature authenticates the body but does not prevent replay. Monotonic ordering prevents state regression.

Central does not persist a receipt and does not deduplicate by payload digest. A queued job holds the accepted report.

Do not run provisioning, billing, or remote calls in the HTTP receiver. Do not put bearer tokens, passwords, or private keys in payloads or delivery logs.

### Delivery limits and recovery

Framework queues after commit and records configured delivery retries. A process can still fail between commit and enqueue. Retries can also be exhausted.

Verify sender workers, scheduler, retry configuration, and Webhook Request Log on staging. A supported DocType is not proof of active delivery.

Webhooks give the normal prompt state update. A paginated scan of known Region and tenant assignments (`central.integrations.servers.reconcile`, every 10 minutes) repairs missed observations.

Use bounded detail checks for active operations and deletion. Do not poll every guest or replace the webhook with a high-frequency fleet loop.

Atlas deletes the Virtual Machine State row through `frappe.db.delete`. That path does not produce a document deletion webhook. Central confirms VM deletion through the correctly scoped Atlas API.

A scoped `404` is also Atlas's response for another tenant's resource. Check the stored Region and tenant before you mark a known resource absent.

Fleet reads, detail reads, and webhook reports share one writer and freshness policy. Keep source observation time separate from local fetch time. An older callback or delayed read must not undo a newer result.

Follow all pages. An incomplete scan, timeout, or server error cannot prove deletion.

### Sleep

A state callback can report stopped when a VM sleeps. It does not carry the desired state.

Read Atlas detail when that difference matters. Do not mark sleep as customer shutdown, cancel a subscription, or report a failed deployment from the callback alone.

Routine synchronization must not call the guest. Signup readiness and user-requested actions may contact Pilot with bounded retries.

## How does Central register Cargo?

Central registers each region's Cargo after a health check. `cargo_connection.register_cargo` calls `CargoClient.configure_webhooks`, which sends Central's receiver URL and a fresh secret. Central stores the secret in `Region.cargo_webhook_secret` and sets `cargo_status` to `Registered`. **Enroll Cargo** on the Region form runs this on demand. `register_pending_cargo` retries Draft regions every 10 minutes.

Cargo reports `service`, `status`, and `service_endpoint`. Central records availability in Service Detail. Do not label a service healthy from a provisioning event.

## How do rename, routes, and TLS work?

Central calls the Pilot Admin API for renames.

| Operation | Pilot endpoint |
|---|---|
| Rename site | `POST /api/v1/sites/<name>/actions/rename` with `new_name` and `keep_old_hostname`. |
| Rename admin domain | `POST /api/v1/settings/admin-domain` with `domain` and `tls`. |

Central stores the returned task ID. An accepted response is not completion. Central keeps the stable Site identity while the Pilot site name changes. Preserve an automatic management alias for recovery.

A Pilot registers its site and custom-domain routes through `central.api.pilot.register_domain` and removes them through `deregister_domain`. Central verifies DNS ownership and applies the proxy route through [Site Domain](../central/infrastructure/doctype/site_domain/SPEC.md).

| Name | Route owner | TLS owner |
|---|---|---|
| Automatic VM name | Proxy computes the VM address. No map write. | Proxy regional wildcard certificate. |
| Friendly regional name | Proxy site map. | Proxy regional wildcard certificate. |
| Customer domain | Proxy domain map to the VM. | Pilot on the VM. |

Atlas provisions the regional proxy and its wildcard certificate. The separate proxy control API applies map changes. Do not give a customer VM an unrestricted regional proxy token.

Wildcard or shared-proxy DNS resolution alone does not prove customer ownership. A domain-specific ownership check is required before a route can move between Teams.

The proxy forwards customer HTTPS as TLS with PROXY protocol v2 to VM port 443. Certificates and renewal stay in Pilot. Central stores the domain record, the operation result, and useful failure information.

## How does the investigator read and change a server?

The Central Investigator is a Flow agent for operators. It is defined in `central/investigator/agents.py` and uses the first enabled Flow Model. It follows the `server-support-guide`, `performance-inspection`, and `virtual-machine-investigation` skills in `skills/`.

| Layer | Read | Change | Contract |
| --- | --- | --- | --- |
| Central | `read_records`, `run_report` | `run_desk_action`, `call_central_api` | The permissions of the user. A change runs a whitelisted document method or a `central.api` method. |
| Pilot | `send_pilot_read_request`, `get_performance_snapshot`, `run_database_query` | `send_pilot_write_request` | Central mints the bench token for each call and attaches it. The agent never sees the token. |
| Insights | `run_region_dashboard_queries` | None | Runs the SQL of an Atlas workbook query on `Region.telemetry_data_source`. Only workbook queries, no free SQL. |
| Atlas | `start_region_investigation`, `get_region_investigation_status`, `get_region_investigation` | None | `POST /investigations` and `GET /investigations/<id>` with the operator client of the region. |

A session starts read-only. A change needs these, in order:

1. The agent asks the user to switch the session to read-write, and the user approves the `switch_to_read_write` call. The switch lasts one hour.
2. The user approves each change call.

A session that approves its own tool calls, such as a Trigger session, cannot switch. `central/investigator/access.py` refuses any change that terminates or destroys a resource, or that returns a login, a console, or a secret. The operator does these in Desk.

The agent can read any Pilot `GET` path except those in `PILOT_DENIED_READ_PATHS`, which return a credential, a login, or a backup file. Performance data (database, monitor, metrics, system, storage, and site monitoring) comes back exact, because a scrub changes numbers and query text. Other results are scrubbed. `run_database_query` runs one `SELECT`, `WITH`, `EXPLAIN`, `SHOW`, or `DESCRIBE` statement in a read-only transaction. A `SELECT` stops after 10 seconds. A read-only transaction does not stop DDL, so the tool refuses any other statement. `PILOT_DENIED_WRITE_PATHS` refuses code, credentials, setup, and SQL changes.

The `Central` and `Pilot` knowledge bases hold the Central documents and the Pilot documents from GitHub, including the generated `docs/admin-api-reference.md`. Each migrate reloads the changed documents. If the load fails, for example without GitHub access, the migrate prints the error and continues. To load them without a migrate:

```sh
pilot --site <site> execute central.investigator.knowledge.load_knowledge_bases
```

## Validation

Run the shared contract tests before deployment. Complete the live journeys in [Staging validation](STAGING_VALIDATION.md) against the actual staging revisions. Mocked responses do not prove VM startup, Pilot login, SSH access, or webhook delivery.
