# WireGuard Device

## Purpose

A WireGuard Device lets one customer device reach the team's servers in one region through the regional WireGuard gateway. Atlas stores no devices, so this record is the only source for a restore. Central stores the public key and the settings the gateway returns. Central never sees the private key.

## Access

`server:view` can list the team's devices. `server:wireguard` can add and remove them. The Owner, Admin, and Developer system roles have `server:wireguard`. A server accepts device traffic only after a member with `server:network` turns on WireGuard access for it.

## Creation

The console makes the key pair in the browser and sends only the public key. A user can also paste a public key from `wg genkey | wg pubkey`. Central gives the device the next free client ID of the team, from 1 to 65535, and registers it with `POST /v1/peers` in `after_insert`. If the gateway refuses, the insert rolls back. The console shows the complete `.conf` file once and does not keep the private key.

## Removal

Delete sends `DELETE /v1/peers`. If the gateway cannot be reached, the device stays as `Removing` and a job every 5 minutes tries again. In Desk, **Retry Removal** tries at once. When a member leaves the team or is removed, their devices go to `Removing`. When the team is archived, all its devices go to `Removing`. Suspension keeps devices, because the servers stop.

## Restore

**Restore WireGuard Devices** on the Region reads `GET /v1/peers` for the node of each device, sends every `Active` device with `PUT /v1/peers`, and stores the settings the gateway returns. A device whose node is gone gets a new node and a new address, so its user must download a new file.
