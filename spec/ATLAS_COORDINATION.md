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

## Server operation contract

Central stores each authorized operation in Resource Action before dispatch. Atlas receives one create or power request. Central saves the accepted VM identity before local finalization. A lost mutation response remains uncertain and must not trigger another remote mutation.

Scoped regional reads confirm VM state and repair interrupted local finalization. A failed read does not prove deletion. A scoped not-found response can confirm deletion and trigger local credential and billing cleanup.

Central builds the automatic management address itself. The regional proxy decodes a VM's mesh address from its hostname label, so Central encodes the same label from the observed mesh address and the cluster's proxy domain. The tenant API does not publish the regional zone, so an operator sets `proxy_domain` on [Region](../central/infrastructure/doctype/region/SPEC.md). A management address alone does not prove Pilot readiness. Pilot creation also receives credential-bound `pilot-central` metadata.

See [Resource Action](../central/infrastructure/doctype/resource_action/SPEC.md) for states, authorization, recovery, accepted quotes, and customer responses.

## Delivery dependencies

The current creation flow requires the Atlas VM API and automatic management hostname. Staging also needs current schema, key trust, a healthy host, available images, and wildcard DNS.

Framework webhook ingestion, signup readiness, and restart completion remain subsequent phases. Their delivery order is in [Delivery](DELIVERY.md). Resize uses the Atlas resize API, which moves a VM to another host when its host cannot fit the new size. Framework state webhooks will supplement repair reads. They must not replace durable intent or make a callback the only recovery path.

Domain and TLS operations belong to Atlas and Pilot. Central will authorize and track those operations when the domain phase starts.

## Validation

Run the shared contract tests before deployment. Complete the live journeys in [Staging integration validation](LOCAL_ENVIRONMENT.md) against the actual staging revisions. Mocked responses do not prove VM startup, Pilot login, SSH access, or webhook delivery.
