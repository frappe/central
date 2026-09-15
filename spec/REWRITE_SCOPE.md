# Central rewrite scope

## Purpose

Atlas and Pilot changed their architecture. Central must follow those changes, remove what they made unnecessary, and expose its own APIs in a form that a client can be generated from. This document records what changed, the object model Central moves to, what Central removes, what Central builds, and in which order.

Read [the Atlas tenant API](../../atlas/atlas/docs/tenant-api.md), [the Atlas security model](../../atlas/atlas/docs/security.md), [the Atlas architecture](../../atlas/docs/architecture.md), [the proxy control daemon](../../atlas/services/http-proxy/docs/control-daemon.md), [the OpenResty data plane](../../atlas/services/http-proxy/docs/openresty.md), and the Pilot specification in [the Pilot repository](https://github.com/frappe/pilot/blob/develop/SPEC.md) before you change a contract this document names.

Use [Local environment](LOCAL_ENVIRONMENT.md) to build a test setup.

`central/billing/**` keeps its domain logic. The rewrite changes its API surface and the shared fields that move.

## 1. What changed outside Central

### 1.1 Atlas is a virtual machine runtime only

Atlas keeps virtual machines, public IPv4 addresses, virtual machine images, the regional proxy cluster, and the regional Cargo server. The Site, Tenant, Pilot, Server, Custom Domain, Subdomain, Root Domain, DNS Provider, TLS Provider, Firewall, VPN Tunnel, Task, Central Settings, and Central Event Log doctypes are deleted. `atlas/atlas/doctype/` holds only `Atlas Settings` and `SSH Task`.

Every method in `central/integrations/atlas.py` calls an endpoint that no longer exists.

| Removed Atlas endpoint | Central caller |
|---|---|
| `atlas.atlas.api.provision.create_vm` | `AtlasClient.create_vm` |
| `atlas.atlas.api.provision.capacity`, `resize_capacity` | `AtlasClient.capacity`, `resize_capacity` |
| `atlas.atlas.api.inventory.tenant_vms` | `AtlasClient.central_vms` |
| `atlas.atlas.api.inventory.available_frappe_versions` | `AtlasClient.available_frappe_versions` |
| `atlas.atlas.api.site.create_site`, `get_site`, `check_subdomain` | `central/api/sites.py` |
| `atlas.atlas.api.central_link.provision_tunnel`, `confirm_tunnel`, `deprovision_tunnel` | `register_atlas`, `remove_tunnel` |
| `run_doc_method` on `Virtual Machine` and `Site` | `vm_action`, `resize_vm`, `terminate_site`, `regenerate_site_login` |
| Atlas to Central event push | `central/api/atlas.py` `event`, `ingest_event` |

### 1.2 The new Atlas interface

Atlas exposes a typed REST API at `/api/atlas`. The OpenAPI document is at `/api/atlas/docs/openapi.json` and is committed at `atlas/clients/openapi/atlas-client.json`. A generated Python client is committed at `atlas/clients/atlas-client` as the `atlas_client` package.

Access is a bearer JSON Web Token.

| Claim | Central value |
|---|---|
| `alg` (header) | `EdDSA` |
| `kid` (header) | `central:<key id>` |
| `iss` | `central` |
| `aud` | `atlas-admin:<region id>` |
| `scope` | `*` |
| `tenant` | `*` |
| `sub`, `iat`, `exp` | Required. `nbf` is optional |

A Central token serves every tenant, so each request must also send the `X-Tenant-ID` header with an unsigned 32-bit integer. Tenant `0` is the system tenant. Atlas gets the Central key set from `central_jwks_url` every 5 minutes and keeps the last valid set after a failure. Atlas refuses a key set that holds anything other than Ed25519 signature keys with a `central:` key identifier.

Routes that Central uses:

- `POST|GET /api/atlas/virtual-machines`, `GET|DELETE /api/atlas/virtual-machines/<id>`
- `POST /api/atlas/virtual-machines/<id>/actions/{start,stop,pause,resume,restart,snapshot,console-token}`
- `PATCH /api/atlas/virtual-machines/<id>/{compute,disk,network}`
- `PUT /api/atlas/virtual-machines/<id>/{ssh-keys,metadata,ip-address}` and `DELETE .../ip-address`
- `GET|DELETE /api/atlas/images/<id>`, `GET /api/atlas/images`, `GET /api/atlas/images/<id>/download`
- `POST|GET /api/atlas/ip-addresses`, `GET|DELETE /api/atlas/ip-addresses/<id>`

The create payload is `image_id`, `vcpus`, `memory_mib`, `disk_mib`, `hostname`, `ssh_keys`, `user_data`, `metadata`, `ip_address_id`, `egress`, `is_privileged`, `sleep_after_idle_seconds`, and the disk and network rate limits. There is no team, no title, no subdomain, and no Frappe version.

A lifecycle route returns `202`. A list response carries `items`, `offset`, `limit`, and `has_more`, with a default limit of 20 and a maximum of 100. An error response carries `error.code`, `error.message`, and `error.fields`. Time fields are Unix seconds.

### 1.3 How a state change reaches Central

Atlas pushes nothing. There is no Central client in Atlas, no webhook, and no event queue. The Atlas realtime module bridges the machine console only. Central reads.

```text
Firecracker on the Metal host
   |  metald reports each machine status
   v
Atlas: atlas.metal_server.usage.enqueue_server_syncs   every 10 seconds
   |  writes one Virtual Machine State row (status, synced_at)
   v
Atlas API
   |
   +-- GET /virtual-machines        last_known_state + state_synced_at, from the stored row
   +-- GET /virtual-machines/<id>   desired_state + current_state + error, read live from Metal
```

| Read | Cost | Freshness | Carries |
|---|---|---|---|
| List | One request per region, paginated | Up to 10 seconds stale | `last_known_state`, `state_synced_at` |
| Detail | One request per machine, reaches the host | Live | `desired_state`, `current_state`, `error`, `compute`, `disk`, `network.mesh_ipv6`, `network.public_ipv4`, `guest.metadata` |

State values are `pending` while the Atlas record is a draft, `terminating` while Atlas is removing it, and otherwise the Metal value: `unknown`, `created`, `running`, `paused`, `stopped`, `failed`, or `destroyed`.

Idle sleep needs both values. `sleep_after_idle_seconds` lets Metal stop a machine to save memory while the desired state stays `running`. A sleeping machine reports `current_state = stopped` and `desired_state = running`, and only the detail route carries `desired_state`. Central must compare the two and must show a sleeping machine as running. Section 5 gives the loop that does this.

### 1.4 The bare metal host is not visible to Central

`Virtual Machine.server` links to `Metal Server` on the Atlas record. It is not in `VirtualMachineResponse`, `VirtualMachineListResponse`, or `VirtualMachineDetailResponse`. The Atlas security model keeps Metal Servers, provider credentials, and bare metal operations with a System Manager.

Central cannot read, store, or show the host of a machine. Central cannot express placement, anti-affinity, or a host preference. Central cannot compute capacity, because Atlas exposes no capacity read. Central holds no host field today. Do not add one.

### 1.5 Pilot self-bootstraps from instance metadata

Atlas injects custom metadata through IMDSv2 at create time. Pilot reads the `pilot-central` attribute and configures itself. There is no callback to Central and no Secure Shell step.

| Key | Meaning |
|---|---|
| `central_endpoint` | Central base URL |
| `central_auth_token` | The durable pilot bearer token |
| `jwks_url` | Where Pilot fetches Central public keys |
| `jwks_audience_id` | The audience each Central token to this host must carry |
| `initial_jwks_cache` | Optional. A key set Pilot stores on disk, so the first token needs no fetch |

`central.api.pilot.enroll` and the bootstrap token are no longer used. Central mints the durable credential before the create call and puts it in `metadata`.

Pilot calls Central at `central.api.pilot.log_token`, `central.api.pilot.metrics_token`, and `central.notification.api.report_pilot_event`, each with the `X-Pilot-Token` header. Pilot verifies a Central token by signature and audience. It accepts `EdDSA` and does not check the issuer.

### 1.6 The regional proxy is a separate control plane

Each region runs a proxy cluster with a control API at `https://proxy.<wildcard-domain>/v1`. Atlas sets it up and then takes no part in routing.

- `GET|PUT /v1/sites`, `PATCH|DELETE /v1/sites/<label>` map one label below the regional wildcard domain to a mesh IPv6 address.
- `GET|PUT /v1/domains`, `PATCH|DELETE /v1/domains/<domain>` map a complete customer domain. The proxy does not end the TLS connection for a custom domain. It sends the TLS bytes to the machine on port 443 behind a PROXY protocol v2 header, so the machine holds the certificate.
- A Central token for the proxy uses `aud = atlas-proxy:<region id>` and `scope = "*"` or `site:* domain:*`. The proxy refuses a token that carries a `tenant` claim.
- A generated client is committed at `atlas/clients/atlas-proxy-client`.

### 1.7 Automatic routing gives every site a free name

The proxy resolves a host below the regional wildcard domain with no map write, when its prefix matches a configured form. The default forms are `site-` and `*-vm-`.

```text
shop-vm-lpc8lqa.par-1.example.com
        |
        +-- label: lpc8lqa, base 36 of (vm_number << 32) | tenant_id
                |
                v
            fdaa:<region>:<tenant>:<vm number>  on port 80
```

`matches_prefix` in `auto_proxy.lua` accepts a wildcard prefix: any non-empty text before `-vm-` resolves to the same machine. So `admin-vm-<label>`, `shop-vm-<label>`, and `staging-vm-<label>` all reach one machine, and **every site on a machine can hold a free automatic name**.

The machine accepts these names because its image carries hostname aliases in `common_config.toml`. `HostnameAliases.set` keys an alias by its pattern, so a machine holds one alias per site.

```toml
[central]
enabled = true
bootstrapped = false

[[central.hostname_aliases]]
type = "admin"
pattern = "admin-vm-*.par-1.example.com"
target = "admin.local"
redirect = false

[[central.hostname_aliases]]
type = "site"
pattern = "shop-vm-*.par-1.example.com"
target = "shop.local"
redirect = false
```

This is the important consequence: **the proxy site map is not needed at all.** Central writes the proxy only for a customer domain. A machine with 1 site or 20 sites costs zero proxy writes.

Two guards in Pilot assume one site and must change. `CentralSetup._alias_site` refuses to set a site alias when the bench holds more than one site, and `pilot setup central` refuses a host with more than one bench. Central sets each alias explicitly instead of letting Pilot infer the only site.

### 1.8 A region is self-hosted and needs no tunnel

An operator builds a region from a TOML file and the `atlas-vm` command. The region brings up Atlas, the proxy, Cargo, the object storage cluster, and the Pilot image builder by itself. Central gets no Secure Shell access to a region. Atlas is reachable over public HTTPS and is protected by the token above. The WireGuard tunnel between Central and Atlas has no remaining purpose.

### 1.9 How a signup machine works

Metal calls it a Sleepy VM. The mechanism has 2 halves.

**Fast start.** Metal keeps a warm artifact on the host. It holds the disk, the guest memory, and the Firecracker state. A new machine skips boot and resumes from it. This is why a machine serves in about 5 seconds.

The warm artifact is found by a key. `vm.WarmImageKey` builds that key from the image reference, the architecture, the root file system checksum, the kernel checksum, the Firecracker compatibility value, and the exact machine shape:

```go
type MemorySnapshotConfiguration struct {
	VirtualCPUCount int
	MemoryMiB       int
	DiskMiB         int
}
```

The shape must match exactly. A machine asked for at any other size gets a cold boot, and the 5 second number is lost. Central must ask for the exact size the image was baked at.

**Idle sleep.** Metal watches network traffic for each machine. After `sleep_after_idle_seconds` with no traffic it saves the guest memory and stops Firecracker. The desired state stays `running` and the observed state becomes `stopped`. The next packet to the machine restores it. The first packet can be lost, so a client must retry.

```text
running -> idle -> save state -> stopped
   ^                              |
   +-------- new IP traffic ------+
```

A sleeping machine keeps its disk, its mesh address, and its automatic name. Only processor and memory are released.

Two rules follow, and both matter.

- **Central must never reach a customer site over HTTP to check it.** That is traffic, and it wakes the machine. A health check on every site would keep the whole fleet awake and remove the benefit. Read machine state from Atlas, which asks the host and not the guest.
- **A plan for the signup product must carry the image's snapshot shape**, not a size a person chose.

## 2. The Central object model

### 2.1 The rule

Central models what it owns or bills. Central mirrors what Atlas owns. Central references what Pilot owns.

```text
Team                Central owns. Carries tenant_id, a 32-bit network isolation boundary.
  | 1:N
Server              Atlas owns the state. Central owns the commercial record.
  |                 One Atlas machine, one Pilot host, one Pilot Credential, one label.
  | 1:N
Site                Pilot owns the state. Central owns the commercial record and the name.
  |                 Holds the bench name as a field.
  | 1:N
Site Domain         Central owns it completely. One hostname with one lifecycle.
```

### 2.2 Why the tenant identifier is an integer

`atlas/atlas/core/mesh_address.py` builds the machine address from it.

```python
address = (0xFDAA << 112) | (region_id << 96) | (virtual_machine.tenant_id << 64) | virtual_machine_number
```

| Bits | Field | Width |
|---|---|---|
| 112-127 | `fdaa` | 16 |
| 96-111 | region | 16 |
| 64-95 | tenant | 32 |
| 0-63 | machine number | 64 |

The wg-mesh design states that the data path uses the tenant field, and that nonzero tenant identifiers are isolated from each other. An eBPF program compares this field to decide whether two machines may exchange traffic. It is network segmentation, not a label.

The automatic proxy label is base 36 of `(machine_number << 32) | tenant_id`, which OpenResty decodes in LuaJIT. `parse_tenant_id` refuses a value outside 0 through 4294967295. Tenant `0` is reserved.

A Frappe document name is renameable. Do not bind a kernel level isolation boundary to one. `Team.tenant_id` is a separate, immutable, indexed, unique integer.

### 2.3 One machine holds one Central team, and many end customers

Every site on a machine shares the machine's tenant identifier, which is an address field the kernel reads. So a machine can never hold the sites of 2 Central Teams.

This is not the same as one business customer for each machine. Ticket 0011 states that an end customer has no Central account and that their identity stays in the site. So a pooled trial machine belongs to one Central Team, which is the platform or the partner, and it holds the sites of many end customers. That is what makes free compute cheap in ticket 0007.

| Boundary | Where it is enforced | What it separates |
|---|---|---|
| Central Team and tenant identifier | The mesh address, by eBPF | One machine from another machine |
| Site | Frappe and Pilot, inside one machine | One end customer from another |

Write both lines into any specification that touches placement. A reader who confuses them will either try to pack 2 Teams onto one machine, which the network refuses, or give every trial customer a machine, which the economics refuse.

### 2.4 Why Server and Site are 2 doctypes and not one

A doctype earns its place when it has its own identity, its own state owner, its own lifecycle verbs, and its own cardinality. Test the 2.

| Test | Server | Site |
|---|---|---|
| Identity | a machine in Atlas, `vm-00013` | a Frappe site, `acme.example.com` |
| Who writes its state | Atlas, from Metal | Pilot |
| Lifecycle verbs | start, stop, resize, terminate | create, rename, back up, install an app, drop |
| How many | 1 | many for each Server |
| Survives the other | Yes. An empty Server is normal | No, but it moves between Servers |

Four of the 5 differ, and the second one decides it. Both repository guides give the same rule: keep one owner for state that can drift. One row would let the machine loop and the site loop write the same `status` field. That is 2 owners for one value, which is the failure the rule prevents.

**The business model needs many sites for each machine.** The decision map says it directly. Ticket 0005 states that the infrastructure gives one guest machine, one bench, and many sites, and that the lever is how many tenants share a machine. Ticket 0007 states that shared trial machines make free compute cheap. Density is the margin, so many sites for each machine is the plan, not an edge case. One row cannot hold many.

**A site moves between machines.** Ticket 0005 asks what graduation means: a new site, a moved site, or a new machine. A trial site on a pooled machine becomes a paid site on its own machine. It keeps its name, its data, its domain, and its subscription. With 2 doctypes that is one field change on `Site.server`. With one doctype the customer's record is destroyed and rebuilt, and the subscription and the domain have to follow.

**End customer identity lives in the site.** Ticket 0011 states it: the end customer has no Central account, and their identity stays in the site. The Site is what a person uses. The Server is capacity.

**Central already models it this way.** `Resource Action.resource_type` is `Server` or `Site`. `Team Member.resource_type` and `Team Invitation.resource_type` are `*`, `Server`, or `Site`. Three doctypes already name these 2 resource kinds, and every capability reads `server:create`, `server:view`, `server:power`.

So the question is already answered in the code. Central holds 2 resource types and refers to them with a `resource_type` and `resource_name` pair. What is wrong is not the model. It is that the machine's table is named `Asset` while everything that points at it says `Server`, and that `Site` is a dead Atlas mirror.

### 2.5 Why Bench is a field and not a doctype

Pilot owns a bench completely. Central neither bills a bench nor routes to one. `Site.bench` holds the name so an operator can find the site on the host. Promote it to a doctype only when Central bills or routes a bench, such as selling a second Frappe version on one machine.

### 2.6 Why Site Domain is its own doctype

A domain has a lifecycle that a field cannot hold.

```text
requested -> dns_verified -> routed -> secured -> active
                 |              |         |
                 +--------------+---------+--> failed
```

`routed` means the proxy domain map holds it. `secured` means the machine holds its certificate. The two are separate systems and each can fail on its own.

### 2.7 Asset is renamed to Server

`Asset` is the machine. `Resource Action`, `Team Member`, and `Team Invitation` all name the type `Server`, and every capability reads `server:*`. The table name is the one thing that disagrees, so the table changes.

The rename touches 163 references outside billing and 194 inside it, and `Subscription.asset_id` is the metering key. It lands in phase 1, not later, for one reason: every phase after it writes code against the name. Renaming late means writing `Asset` everywhere first and then changing it again. Phase 1 is when the codebase is smallest.

Billing holds 98 test files and 19,757 lines of tests, so the rename is verifiable rather than hopeful. `Subscription.asset_id` and `Subscription.service_subject` are 2 fields for one idea. They become `subject_type` and `subject_name`, which matches the pair the other 3 doctypes already use, and which lets a subscription bill a Server or a Site.

### 2.8 What signup does not need

The signup image already holds a bench and one site named `site.local`, and the alias `site-*` already points at it. So signup creates a machine, and the site is simply there.

| Step | Signup | Second site, or the server product |
|---|---|---|
| Create the Atlas machine | Yes | No, it exists |
| Write the Pilot credential into the metadata | Yes | No |
| Ask Pilot to create a site | **No** | Yes |
| Write a proxy route | **No** | No, the automatic name covers it |
| Write a Pilot hostname alias | **No**, the image has it | Yes |
| Record the Site in Central | By discovery | By provisioning |

This is the simplification. Signup needs a machine and nothing else. Central records the Site by reading what Pilot reports, not by asking Pilot to build one.

The site provisioning path is still needed, for the second site on a machine and for the server product. It is no longer on the signup critical path, so it moves out of the first release.

## 3. Remove from Central

| Path | Reason |
|---|---|
| `central/api/atlas.py` | `event`, `register`, `sizes`, `images`, and `ping` have no caller. |
| `Atlas Event` doctype and its rows | No event push. |
| `verify_atlas_webhook`, `_authenticate_atlas_webhook`, `signature_matches`, `ingest_event`, `apply_event`, `_on_vm`, `_on_vm_deleted`, `_on_site` | No event push. |
| `central/mirror.py` | Last-writer-wins exists to merge a push with a pull. A loop has one writer. |
| `Central Tunnel Settings` doctype | No tunnel. |
| `Host Task` doctype, `central/host_task.py`, `central/scripts_catalog.py`, `central/scripts/`, `scripts/sudoers.d/central-tunnel` | These run the WireGuard hub scripts only. |
| `register_atlas`, `_register_local`, `_ensure_service_user`, `_ensure_service_role`, `_rotate_service_credentials`, `_rotate_webhook_secret`, `_verify_over_tunnel`, `_peer_endpoint`, `_rollback`, `remove_tunnel` | Registration is configuration on each side, not a handshake. |
| `spec/TUNNEL.md` | Describes a removed mechanism. |
| `central.api.pilot.enroll`, `mint_bootstrap_token`, `verify_bootstrap_token`, `PilotCredential.reserve`, the Redis single-use guard | Replaced by metadata injection. |
| `AtlasClient.capacity`, `resize_capacity`, `_get_bounded` | Atlas exposes no capacity read. |
| `AtlasClient.available_frappe_versions`, `_available_versions`, `_validate_frappe_version`, `_stamp_frappe_version`, `FALLBACK_FRAPPE_VERSIONS` | Replaced by the image catalog. |
| `AtlasClient.create_site`, `get_site`, `regenerate_site_login`, `terminate_site`, `check_subdomain` | Atlas has no site. |
| `Atlas Instance` doctype | Merged into `Region`. |
| `Server` fields `login_url`, `login_url_expires_at`, `last_event_at` | Atlas mints no login URL and pushes no event. |
| `Site` fields `login_url`, `login_url_expires_at`, `last_event_at`, `cluster` | Same, and the region comes from the Server. |
| `Resource Action.atlas_task` | Atlas has no Task doctype. |
| Tests `test_atlas_webhook_signature.py`, `test_atlas_register.py`, `test_enroll.py`, `test_frappe_version.py`, `test_atlas_sync.py` | Cover removed behavior. |

Write a patch for each doctype and field that a shared site holds. The `Asset` to `Server` rename needs its own patch. Drop the removed doctypes outright.

## 4. Change and add

| Path | Change |
|---|---|
| `central/integrations/atlas.py` | Delete. Replaced by `central/integrations/atlas/` with the client, the token, and the loop. |
| `central/sso.py` | Ed25519 with a `central:` key namespace. A region token minter (`iss=central`, `aud=atlas-admin:<region id>`, `scope=*`, `tenant=*`). A proxy token minter (`aud=atlas-proxy:<region id>`, no `tenant`). Drop the bootstrap scope. |
| `Central SSO Settings`, `central/api/jwks.py` | An Ed25519 key set with namespaced identifiers and more than one active key. Atlas refuses a set that holds an RSA key, so Central cannot publish both. |
| `Region` doctype | Absorbs `Atlas Instance`: `region_id`, `wildcard_domain`, `mesh_address_prefix`, `atlas_base_url`, `proxy_control_url`, `status`. One region, one Atlas, one proxy cluster. |
| `Team` doctype | Add an indexed, unique, immutable `tenant_id`. |
| `Server` doctype, renamed from `Asset` | `memory_mib` and `disk_mib` replace the megabyte and gigabyte fields. Add `image`, `mesh_ipv6`, `sleep_after_idle_seconds`, `desired_state`, `tenant_id`, `auto_proxy_label`, `pilot_credential`. |
| `Site` doctype | Stops being an Atlas mirror. Links to `Server`. Adds `bench`, `auto_proxy_name`. Drops `pilot_credential_id`, which moves to the Server. |
| `Site Domain` doctype | New. One hostname, its state machine, its proxy map state, and its certificate state. |
| `Virtual Machine Image` catalog | New. A record per usable Atlas image per region, refreshed from `GET /api/atlas/images`, holding the Frappe version and the Pilot release. Replaces the Frappe version list. |
| `central/integrations/proxy.py` | New. Domain map writes over the proxy control API. The site map is not used. |
| `central/regions/mesh.py` | New. The automatic label, the automatic host name, and the mesh address, from the machine number and the tenant. |
| `central/api/servers.py` | Image selection replaces version validation. The capacity gate goes. Split by concern. |
| `central/api/sites.py` | Drives the Pilot Admin API. Subdomain and domain rules move to Central. |
| `Pilot Credential` doctype | Issued at create time, not at enrolment. Belongs to the Server. |
| `central/integrations/cargo.py`, `central/api/cargo.py` | Atlas provisions Cargo with `CENTRAL_URL=https://central.invalid`. Needs a decision with the Atlas owner. |

### 4.1 What the console reads, and what the region merge changes

The server map does not read `Atlas Instance`. `useServerMapData` calls `central.api.servers.registry`, which reads the `Asset` and `Site` rows of one team. The map plots a team's own machines and sites, and it takes the position from the region each row names.

Only the region picker reads `Atlas Instance`, through `central.api.servers.list_instances`. That endpoint already merges 2 sources:

| Source | Fields |
|---|---|
| `Atlas Instance` | `region`, `status`, `reachable` |
| `Region` | `display_name`, `provider`, `country_code`, `latitude`, `longitude` |

So `Atlas Instance` gives the console 3 values and nothing else. Every value a person sees already lives on `Region`. `useRegions` feeds the New Server picker, the servers page, the server overview dialog, and the 2 team dialogs that grant a role on one region.

After the merge, `list_instances` reads `Region` alone and filters on `status`. The merge is invisible to a user.

It also removes a permission bypass. `list_instances` reads with `frappe.get_all` and a comment that says `Atlas Instance` is locked to System Manager because it holds per-instance API credentials. After phase 1 there are no per-region credentials, because Central signs a token with its own key. `Region` then holds no secret at all, so a Central User can read it through normal permissions and the bypass goes.

`reachable` changes meaning. Today the tunnel verify sets it. It becomes derived from the age of the last reconciliation pass, which is rule 9 of section 5.

Two renames follow, and both are cheap and Central-only:

- `central.api.servers.list_instances` becomes `regions`. It is named for a doctype that will not exist.
- The capability `cluster:view` becomes `region:view`. There is 1 production call site, 1 entry in `central/iam.py`, a fixture, `CAPABILITIES.md`, and the tests. Pilot does not read this capability, so the `fc_teams` claim change reaches nothing outside Central.

## 5. The reconciliation loop

Central does not poll. Central reconciles, which is the pattern the rest of the stack already uses.

```text
Metal   reconciles  Firecracker    internal/reconciler: a pass at startup, on an interval, and after a request
Atlas   reconciles  Metal          settle(): "Metal is the authority"
Central reconciles  Atlas          this section
```

Rules:

1. **Atlas is the authority.** Central writes only a value a read returned. There is no optimistic transition.
2. **Each pass converges.** A pass recomputes the comparison. A missed pass is harmless because the next pass corrects it. There is no ordering requirement and no merge, which is why `central/mirror.py` is deleted.
3. **Absence is a signal.** A `404` on the detail route means terminated, not failed.
4. **Jobs are deduplicated.** `job_id=f"central||region-sync||{region}"` with `deduplicate=True` and a per-job timeout, as `enqueue_server_sync` does in Atlas. A slow region cannot queue a second pass.
5. **Two tiers.** A fleet pass per region on the list route at fixed cost. A focused pass per machine with a deadline.
6. **A user action kicks the focused pass.** After an action route returns `202`, enqueue the focused pass at once instead of waiting for the interval. This gives event latency with loop correctness.
7. **Read both states.** `current_state` with `desired_state`, so a sleeping machine reads as running.
8. **Every focused pass is bounded.** On deadline the Resource Action fails and leaves a readable error on the record.
9. **Staleness is visible.** Store and show `last_synced_at`. Degrade a region on pass age.
10. **Never reach the guest.** Every read goes to Atlas, which asks the host. An HTTP check against a customer site would wake a sleeping machine. Section 1.9 explains why.

Verification:

- A fake Atlas with a scripted state machine that covers a stuck `pending`, a flapping state, a `404` during a pass, a `500`, and a timeout. Every path must reach a terminal Resource Action.
- A property test: for any response sequence the mirror converges to the last response and the loop stops.
- An idle sleep test that asserts a sleeping machine renders as running.
- A drift test in tier B: create a machine in the Atlas Desk out of band and assert the fleet pass finds it.
- Metrics: pass age per region, pass duration, focused passes in flight, and deadline expiries. Alert on pass age.

One list request per region per interval. Atlas's own host sync runs every 10 seconds, so a faster Central interval buys nothing.

## 6. The Central public API

### 6.1 The problem

Central's surface is `@frappe.whitelist` remote procedure calls. There is no schema, no status code contract, no error shape, and no way to generate a client. The console re-implements each call by hand, and a SaaS product cannot be built on it.

Three domains need a described API: **server lifecycle**, **billing**, and **signup**.

### 6.2 The package

Build the typed layer in Central as `central/api/core/`, shaped so it can be extracted later. Atlas's version is about 980 lines and is the reference, but it is coupled to Atlas: `core/base.py` imports `TENANT_HEADER`, `MAXIMUM_TENANT_ID`, and `get_current_tenant_id` from `atlas.auth.identity`, and `get_owned_document` is Atlas-shaped. Central's version keeps those out.

| In the core | In the app |
|---|---|
| `Router`, `RouteHandler`, registration into `API_URL_MAP` | The authentication hook |
| Binding for `payload`, `query`, and path parameters | Tenancy and request headers |
| OpenAPI generation and the reference page | The permission model |
| `ApiError` and the error envelope | Domain models and ownership reads |
| `ListQuery`, `Page`, `ApiResult`, `StrictModel`, `PatchPayload` | |

The core takes a hook for extra OpenAPI parameters, so an app adds its own headers without the core knowing them.

### 6.3 The surface

`/api/central/v1` with one router per domain: `servers`, `sites`, `domains`, `billing`, `signup`, `teams`. The authentication hook is the one gate. Each route resolves a team and calls `can(user, team, capability)`. The error envelope matches Atlas, so one client handles both planes.

Generate and commit `clients/openapi/central.json` and a `central_client` package, regenerated in continuous integration and failing on drift. Generate the console's TypeScript client from the same document.

The existing whitelisted methods are deleted as each domain moves. Central is not in production, so no domain is served twice.

## 7. Standards work outside billing

Central holds about 19,700 lines outside `central/billing/**`.

- One `SPEC.md` per module, naming its owner, its state, and its boundary. `spec/README.md` is the router.
- Layout by domain: identity, regions, servers, sites, routing, services, notifications. Remove `central/utils/`.
- A route parses, authorizes, and delegates. Behavior lives with its owner.
- Every team-scoped doctype needs a `permission_query_conditions` entry and a `has_permission` entry, with a test for each rule, the denial case, and the cross-team case.
- Desk: apply the list, form, navigation, and action rules in `CLAUDE.md` to `Server`, `Site`, `Site Domain`, `Pilot Credential`, `Resource Action`, `Region`, and `Cargo Instance`.
- Type hints on every public function and route. Files between 100 and 500 lines. Cyclomatic complexity of 8 or less.

## 8. Dashboard

- Server creation: sizes in MiB, an image picker instead of a version picker, no capacity gate.
- Server state: a bounded poll, a clear waiting state, and a sleeping machine shown as running.
- Onboarding: show the automatic name first and offer a custom domain later.
- Sites: a site list under a server, and a site creation flow that drives Pilot.
- Domains: a screen for the domain, its DNS record, its routing state, and its certificate state.
- Console: the Atlas console token flow.
- Generate the TypeScript client from `clients/openapi/central.json` and delete the hand-written call sites.
- Three tier components, thin pages, fetching in composables.

## 9. Remaining decisions

1. **Atlas client.** The recommendation is to use the committed `atlas_client` package, wrapped by `central/integrations/atlas/client.py` which owns the token, the tenant header, timeouts, and the error mapping. It is 9,419 lines across 77 modules and adds `httpx` and `attrs`, but Atlas regenerates it in continuous integration and fails on drift, so Central gets a contract-checked surface without maintaining one.
2. **Capacity.** The plan menu stops filtering on capacity, or Atlas adds a route.
3. **Cargo registration.** How a Cargo host learns its real Central URL and bootstrapping token.
4. **Datum tokens.** Datum must accept `EdDSA` before Central drops RSA.
5. **Public API identity.** A team API key, an OAuth token, or both.

Settled: the object model in section 2, the `Asset` rename in phase 1, patches only where a shared site holds data, the typed API core built in Central, and Central building both sides of the custom domain flow.

## Work in other repositories

| Repository | Change | Phase |
|---|---|---|
| Atlas | Add `memory_snapshot_vcpus`, `memory_snapshot_memory_mib`, and `memory_snapshot_disk_mib` to `ImageResponse`, and regenerate `atlas-client`. Without them Central cannot be sure a machine starts warm. | 2 |
| Pilot | Add a metadata base override beside `PILOT_METADATA_KEY`, so the bootstrap can be tested without a machine. | 2 |
| Pilot | Relax `CentralSetup._alias_site` and `pilot setup central` for a host with many sites. | 5 |
| Pilot | Add the endpoint that issues a certificate for a Central-managed domain. | 5 |

Each is a separate pull request in its own repository. Write the Atlas change first, because phase 2 needs it.

## 10. The plan

[Delivery](DELIVERY.md) turns each phase below into its pull requests, and records where billing meets the rewrite.


Decisions already taken: patches only where a shared site holds data; the typed API core is built in Central and extracted later; Central builds both sides of the custom domain flow; `Server`, `Site`, and `Site Domain` are separate doctypes.

### Phase 0. Identity and region

Add `Team.tenant_id`, immutable, indexed, unique, with a patch that allocates one to each existing Team. Merge `Atlas Instance` into `Region`. Move `Central SSO Settings` to Ed25519 with a `central:` key namespace and more than one active key. Serve that set from `central/api/jwks.py`. Add the region and proxy token minters.

Verify in tier B: Atlas fetches the Central key set without an error, and a Central token reaches `GET /api/atlas/virtual-machines` and is refused for another tenant.

Unblocks every Atlas call.

### Phase 1. Demolition and the rename

Delete everything in section 3, with its patches and its tests. Rename `Asset` to `Server` across Central, and replace `Subscription.asset_id` and `Subscription.service_subject` with `subject_type` and `subject_name`. The rename and the billing subject change are separate pull requests.

Verify: `ruff check central`, the whole suite including the 98 billing test files, and no import that resolves to a deleted module.

Unblocks a clean base, and stops every later phase writing the wrong name.

### Phase 2. The Atlas client and the image catalog

Add the 3 memory snapshot shape fields to the Atlas `ImageResponse` and regenerate `atlas-client`. Add the Pilot metadata base override. Then add `central/integrations/atlas/` over the generated client, with the token, the tenant header, timeouts, and the error mapping onto `central/errors.py`. Add the image catalog refreshed from `GET /api/atlas/images`, holding the Frappe version, the Pilot release, and the snapshot shape.

Verify: tier A contract tests against the committed OpenAPI document, and tier B reads against a real Atlas site.

Unblocks the server lifecycle and a guaranteed warm start.

### Phase 3. Server lifecycle and the loop

Rework `Server` to the new fields. Rewrite create, read, power, resize, and terminate. Build the fleet pass and the focused pass with the rules in section 5. Complete a Resource Action from a pass, not an event. Carry `sleep_after_idle_seconds` from the plan, and take the machine size from the image snapshot shape so a signup machine starts warm.

Verify: the loop tests in section 5, and a warm start measured in tier C.

Unblocks the console and billing accuracy.

### Phase 4. Boot credential, and signup works

Issue the Pilot Credential before the create call and put the `pilot-central` document in `metadata`, with `initial_jwks_cache`. Bind the credential to the Server. Record the Site by discovery, from what Pilot reports.

**Signup is complete at the end of this phase.** It needs a machine and its metadata, and nothing else. Section 2.8 explains why.

Verify: tier C, from the create call to a login on `site-<label>.<wildcard>`. Tier A once Pilot gains a metadata base override.

Unblocks the self-serve product.

### Phase 5. Sites, routing, and domains

This phase serves the server product and custom domains. Signup does not wait for it.

Add `central/regions/mesh.py` for the label, the automatic host name, and the mesh address. Make `Site` a Central record that drives the Pilot Admin API for a second site, with its own `<prefix>-vm-<label>` name and a matching Pilot hostname alias. Add `Site Domain` with its state machine, the proxy domain map write, and the certificate request on the machine.

This phase changes Pilot as well: relax `CentralSetup._alias_site` and `pilot setup central` for many sites, and add the endpoint that issues a certificate for a Central-managed domain. Specify that endpoint and review it before writing either side.

Verify: tier C, a second site on one machine and a working custom domain.

Unblocks the server product.

### Phase 6. Cargo and telemetry

Close the `CENTRAL_URL=https://central.invalid` gap with the Atlas owner. Confirm Datum accepts `EdDSA`.

Unblocks metrics and logs.

### Phase 7. The typed API

Build `central/api/core/`. Move the server lifecycle, billing, and signup domains onto `/api/central/v1`. Commit the OpenAPI document and the generated clients, with a drift check in continuous integration. Move the billing API surface without changing its domain logic.

Unblocks SaaS and the console client.

### Phase 8. Dashboard

Section 8.

### Order

Phase 1 runs before phase 2, so the new client is written into empty space. The standards work in section 7 runs inside each phase for the module that phase touches, not at the end.
