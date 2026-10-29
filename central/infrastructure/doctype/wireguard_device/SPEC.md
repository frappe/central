# WireGuard Device

## Purpose

A WireGuard Device lets one customer device reach the team's servers in one region through the regional WireGuard gateway. Atlas stores no devices, so this record is the only source for a restore. Central stores the public key and the settings the gateway returns. Central never sees the private key.

## Access

`server:wireguard` can list and add the team's devices and remove their own. Only an operator can change a device after it is added. `team:manage_members` can also remove a device of any member. The Owner, Admin, and Developer system roles have `server:wireguard`. A team has at most 100 devices. A server accepts device traffic only after a member with `server:network` turns on WireGuard access for it, and, when its firewall is on, adds a rule that allows the device's address.

## Creation

The console makes the key pair in the browser and sends only the public key. A user can also paste a public key from `wg genkey | wg pubkey`. Central gives the device the highest client ID of the team plus one, up to 65535, and registers it with `POST /v1/peers` in `after_insert`. If the gateway refuses, the insert rolls back. The console shows the `.conf` file once, as a QR code for the mobile app and as a download. It does not keep the private key. The QR code is made in the browser.

## Removal

Delete sends `DELETE /v1/peers`. If the region no longer has a gateway, delete removes only the record. If the gateway cannot be reached, the device stays as `Removing` and a job every 5 minutes tries again. In Desk, **Remove Device** removes a lost device and **Retry Removal** tries a `Removing` device again at once. When a member loses `server:wireguard`, all of their devices go to `Removing`. This happens when they leave the team, are removed, get a role without it, or their role loses it. A disabled user loses their devices in every team. When the team is archived, all its devices go to `Removing`. Deleting a team deletes its devices and takes them off the gateway first. Suspension keeps devices, because the servers stop.

## Restore

**Restore WireGuard Devices** on the Region reads `GET /v1/peers` for the node of each device. It sends every `Active` device with `PUT /v1/peers` and stores the settings the gateway returns. A device whose node is gone gets a new node and a new address, so its user must download a new file. A restore does not stop devices that are added or removed while it runs, so run it again if a member changed a device during the restore.
