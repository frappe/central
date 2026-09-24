# Atlas and Pilot coordination

## Purpose

Central owns identity, Team capabilities, catalog policy, and billing. Atlas owns regional images, virtual machines, placement, and proxy routing. Pilot owns the benches and sites inside a server. Cargo builds the prepared images.

Central reaches each service through `central/integrations/`. Team authorization follows [IAM](IAM.md) and [Capabilities](../CAPABILITIES.md).

## Regional authentication

Region stores the direct regional URL and numeric region ID, alongside its geography and display identity. Central signs a short-lived token for that region. Each request carries the Team tenant ID in `X-Tenant-ID`. Atlas verifies the token and enforces the tenant boundary.

System images form a shared regional catalog. The tenant header identifies the authorized caller. It does not make those images Team-owned. Operator connection checks use the system tenant.

See [Regional configuration](../central/infrastructure/doctype/region/SPEC.md) for trust setup and connection checks.

## Image contract

Central fetches available System images when the customer selects a region and Image Offering. An offering contains presentation fields, allowed flows, and required tags. It does not store regional builds.

Atlas must return the following fields with each build:

| Field | Central use |
|---|---|
| ID, title, tags, and architecture | Identify and describe the selected build. |
| Enabled flag and availability state | Show only usable builds. |
| Root filesystem size in MiB | Reject plans whose disk cannot hold the image. |

Cargo's current Pilot image contains `default-bench` and `site.local`. Server and signup flows use that image layout. Ubuntu uses a base image and requires SSH keys. See [Image Offering](../central/infrastructure/doctype/image_offering/SPEC.md) for selectors and pagination.

Server creation has two customer options, stored on `Virtual Machine` as `has_public_ipv6` and `is_firewall_enabled`. Central sends an option to Atlas only when the customer selects it:

| Option | Atlas create field |
| --- | --- |
| Public IPv6 | `public_ipv6: "auto"` |
| Firewall | `firewall.enabled: true` with the rules below |

The firewall allows all inbound traffic from the mesh prefix `fdaa::/16`, because an enabled Atlas firewall also filters mesh traffic and the regional gateway reaches a machine over the mesh. It also allows inbound ICMP, inbound TCP ports 22, 80, and 443, and all outbound traffic. Without the option, Central sends `firewall.enabled: false`, which permits all traffic.

Atlas reports the guest public IPv6 as a `/128` prefix. Central stores the address without the prefix length in `public_ipv6`, and stores `public_ipv4` as reported. The overview shows `ssh root@<address>` for an Ubuntu server and uses the IPv6 address first. See [Team SSH Key](../central/infrastructure/doctype/team_ssh_key/SPEC.md) for selected keys and rotation.

A member with `server:console` can open the web console of a running Ubuntu server. Central asks Atlas for a single-use console token in `ssh` mode through `POST /virtual-machines/{id}/actions/console-token`, and returns `<region base URL>/vm_console#token=<token>`. The dashboard asks for a new token each time a member opens the console from the overview or the server actions, because Atlas spends the token on first use. It opens the Atlas URL in one popup window per server, so a second request replaces the session in that window. The token expires after 60 seconds and stays in the URL fragment, so the browser does not send it to a server.

## Server operation contract

Central stores each authorized operation in Resource Action before dispatch. Atlas receives one create or power request. Central saves the accepted VM identity before local finalization. A lost mutation response remains uncertain and must not trigger another remote mutation.

Scoped regional reads confirm VM state and repair interrupted local finalization. A failed read does not prove deletion. A scoped not-found response can confirm deletion and trigger local credential and billing cleanup.

Central builds the automatic management address itself. The regional proxy decodes a VM's mesh address from its hostname label, so Central encodes the same label from the observed mesh address and the region's proxy domain. The tenant API does not publish the regional zone, so an operator sets `proxy_domain` on [Region](../central/infrastructure/doctype/region/SPEC.md). A management address alone does not prove Pilot readiness. Pilot creation also receives credential-bound `pilot-central` metadata.

See [Resource Action](../central/infrastructure/doctype/resource_action/SPEC.md) for states, authorization, recovery, accepted quotes, and customer responses.

## Delivery dependencies

The current creation flow requires the Atlas VM API and automatic management hostname. Staging also needs current schema, key trust, a healthy host, available images, and wildcard DNS.

Framework webhook ingestion, signup readiness, and restart completion remain subsequent phases. Their delivery order is in [Delivery](DELIVERY.md). Resize uses the Atlas resize API, which moves a VM to another host when its host cannot fit the new size. Framework state webhooks will supplement repair reads. They must not replace durable intent or make a callback the only recovery path.

Domain and TLS operations belong to Atlas and Pilot. Central will authorize and track those operations when the domain phase starts.

## Validation

Run the shared contract tests before deployment. Complete the live journeys in [Staging integration validation](LOCAL_ENVIRONMENT.md) against the actual staging revisions. Mocked responses do not prove VM startup, Pilot login, SSH access, or webhook delivery.
