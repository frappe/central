# Products

## Purpose

A Product is an app that customers can sign up for from its own page, such as Raven. The page links to `/dashboard/signup?product=<product key>`. Central starts the trial on an image that has the app installed. A signup without `?product=` is a plain trial and does not change.

The Signups module holds Product, so it can move into its own app later.

## Configuration

System Managers create and edit products in Desk. Nobody else can read the DocType.

| Field | Rule |
|---|---|
| Product Key | Lowercase letters, numbers and hyphens. It is the record name and cannot change after creation. |
| Title | The product name. |
| Enabled | A disabled product refuses new signups. Its existing sites keep running. |
| Logo | The product logo for the signup pages. |
| Subtitle | Optional. A short line for the signup pages. |
| Signup App | The app module name, such as `raven`. Cargo tags the image that has this app installed with `app=<signup app>`. |

Example: Product Key `raven`, Title `Raven`, Signup App `raven`. The signup link is `/dashboard/signup?product=raven`.

## Operation

`GET central.api.signups.get_product(product)` returns the title, logo and subtitle of an enabled product, or nothing. Guests can call it, limited to 60 calls per minute for each IP address.

`central.api.sites.create_trial_site(subdomain, request_key, team, product)` takes the product key. Central refuses an unknown or disabled product before it asks the region for an image. See [Trial sites](../../../infrastructure/doctype/site/SPEC.md#configuration) for how the image is chosen.

A Product needs a Cargo image of type Apps for its signup app in the region. Without one, the signup stops with "No trial image is available right now."
