# Team SSH Key

## Purpose

A Team SSH Key stores one public login key. A server records the keys selected when the Team creates it. Central sends their public values to Atlas. Central does not store private keys.

## Access

`server:view` can list the Team's keys. `server:ssh-key` can add, rotate, retry, and delete them. The Owner, Admin, and Developer system roles have `server:ssh-key`. A key from another Team cannot be selected for a server.

## Creation

The server creation form lists the active Team's keys. The Add SSH key action creates a Team SSH Key and selects it in the form. Central saves selected key links on the Virtual Machine and sends their public values in the Atlas create request. The saved request holds only the key links. Central reads the public values when it sends the request, so a retry sends the current value of a rotated key. SSH keys are optional for every image. A server without keys is reachable through the web console.

## Rotation

Changing a public key queues synchronization for each live server that selected it. The integration layer sends the complete selected key list through Atlas `PUT /virtual-machines/{id}/ssh-keys`. It serializes updates for one server and reads the latest public values before each PUT. The key record shows the names of servers that failed, and an operator or key manager can retry. In Desk, **Retry Sync** on the key queues the synchronization again. Delete is refused while a server, a pending creation, or a failed creation that can still be retried selects the key.

## Validation

Central accepts one valid OpenSSH public key per record and stores its SHA256 fingerprint. It rejects duplicate key material within a Team.
