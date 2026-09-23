# Image offerings

## Purpose

An Image Offering is a customer-facing choice, such as Pilot or Ubuntu. Central owns its name, logo, description, allowed flows, and required image tags. Atlas owns regional image builds and availability. Cargo builds the prepared Pilot images.

An offering has no Team, regional image ID, copied software version, resource size, or synchronization job. System images are shared across Teams. Private Machine images are outside this catalog.

## Configuration

System Managers can create and edit offerings. Central Users can read them. The stable offering key cannot change after creation. Each required tag has one nonempty key and value. Duplicate keys and query separators are rejected.

The default Pilot offering selects `purpose=pilot` for Server and Signup flows. Cargo's current image includes `default-bench` and `site.local`. Both flows retain that site. The Ubuntu offering selects `purpose=base` and `os=Ubuntu` for Server flows only. No layout tag is assumed.

Operators can upload a logo and set a description. The console shows image choices as logo buttons. Uploaded logos take precedence over the bundled Pilot and Ubuntu defaults. Regional versions come from Atlas tags, including `pilot_version` and `frappe_version`. Frappe version 16 and Nightly are Frappe choices, not Pilot release numbers.

## Operation

`central.api.images.list_offerings(team, flow)` returns enabled presentation records for Server or Signup. It does not claim regional availability.

`GET central.api.images.list_images(team, region, offering, flow, offset)` reads one page from the selected region. It requires `server:view` in the Team through Central IAM. Central derives the tenant header from that Team. The regional catalog remains shared.

`GET central.api.images.eligible_plans(team, region, offering, image_id, snapshot)` returns the billing catalog filtered by the selected image's minimum disk size. A snapshot replaces the offering and image inputs. The response keeps billing's `cluster` price dimension because the billing catalog owns that model.

The integration requests System images with every saved offering tag. It rejects private images and mismatched responses. It returns available, enabled builds with their IDs, titles, architecture, disk size, and tags. It does not return transfer errors or private regional configuration.

Follow `next_offset` until it is null. A page can contain no available images and still have another page. Regional failures use the customer-safe resource error envelope and remain visible in the page. They are not converted into empty catalogs. Draining and Disabled regions do not accept customer discovery for creation.

The operator's **Preview Regional Images** action uses the saved selector and system tenant. It supports subsequent pages. It creates no remote resources.

## Installation and migration

`ensure_default_offerings` creates missing Pilot and Ubuntu records on installation. The `seed_image_offerings` patch runs the same function on existing sites. Repeated execution preserves operator edits, including disabled offerings.

## Dependencies

The server plan menu offers only positive whole-vCPU counts because Atlas does not expose CPU quotas. Custom configurations follow the same restriction. Existing fractional plans remain in the billing catalog but are unavailable for server creation. Memory can remain below one GiB, provided its MiB value is a positive whole number.

Central sends the selected regional image ID when creating a server. Atlas and Cargo own image maintenance. Atlas and Metal own warm-start selection and cold-boot fallback. Central filters plans by image disk size and revalidates image availability before accepting creation. See [Resource Action](../resource_action/SPEC.md) for provisioning and recovery.

## Validation

Run `central.tests.test_image_offerings` and `central.tests.test_regional_configuration`. They cover permissions, cross-Team denial, pagination, invalid responses, selector validation, regional connection failures, and idempotent defaults.
