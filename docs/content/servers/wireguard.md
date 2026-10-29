---
title: WireGuard devices
description: Connect a laptop or phone to your servers over their private addresses with WireGuard, and see which roles can do what.
---

# WireGuard devices

A WireGuard device is a laptop, phone, or other computer that reaches your servers over their private IPv6 addresses. The traffic goes through an encrypted tunnel to the WireGuard gateway of the region. The servers do not need a public address or an open SSH port.

A device belongs to the team and to one region. It reaches only the servers of your team in that region that have **WireGuard access** on.

::: info
WireGuard is available only in regions that have a WireGuard gateway. If no region has one, the **WireGuard** settings show that it is not available yet.
:::

## Add a device

1. Click your name at the bottom of the sidebar, then **My profile**. In the settings, click **WireGuard**. You can also press `Ctrl+,` or `⌘+,` to open the settings.
2. Click **Add**. If the team has no devices yet, click **Add device**.
3. Type a **Name**, such as `Work laptop`.
4. Select the **Region**. The dialog shows the servers in that region and which ones the device can reach.
5. Click **Add device**.

Your browser makes the key pair. Only the public key goes to Frappe Cloud. The dialog then shows a QR code and a **Download .conf** button. Both hold the private key. Scan the code on a phone, or download the file on a computer. The file has the name of the device, such as `work-laptop.conf`.

::: warning
The QR code and the file show only once. If you lose the file, delete the device and add it again.
:::

::: tip
A device reaches a server only after you turn on [WireGuard access](#let-a-device-reach-a-server) for that server.
:::

### Use your own key pair

To keep the private key off the browser, make the key pair yourself:

```bash
umask 077
wg genkey > private.key
wg pubkey < private.key
```

`umask 077` keeps the private key readable by you alone.

In the dialog, select **I have my own key pair** and paste the public key. Never paste the private key.

When you open **View settings** later, the file has `<your private key>` in place of the key. Copy the file and put your private key there before you import it.

## Connect

Install the [WireGuard app](https://www.wireguard.com/install/) on the device. Then follow the steps for the device.

### Windows

1. Open WireGuard.
2. Click **Import tunnel(s) from file**.
3. Select the `.conf` file.
4. Click **Activate**.

### macOS

1. Open WireGuard.
2. Click **Import Tunnel(s) from File**.
3. Select the `.conf` file.
4. If macOS asks, allow the VPN configuration.
5. Click **Activate**.

### Android

1. Open WireGuard.
2. Tap **+**.
3. Tap **Scan from QR code**.
4. Scan the QR code in the dialog.
5. Tap the switch next to the tunnel.

### iPhone and iPad

1. Open WireGuard.
2. Tap **Add a tunnel**.
3. Tap **Create from QR code**.
4. Scan the QR code in the dialog.
5. If iOS asks, allow the VPN configuration.
6. Tap the switch next to the tunnel.

### Linux

1. Install the WireGuard tools, for example `sudo apt install wireguard`.
2. Copy the file to `/etc/wireguard/`, for example `sudo cp work-laptop.conf /etc/wireguard/`.
3. Start the tunnel with `sudo wg-quick up work-laptop`. Use the file name without `.conf`.
4. To stop the tunnel, run `sudo wg-quick down work-laptop`.

### Connect to a server

When the tunnel is on:

1. In the settings, open the row menu of the device.
2. Click **View settings**.
3. Click the SSH command of a server to copy it.
4. Run the command:

   ```bash
   ssh root@2001:db8:4a:6::10
   ```

   The dialog shows the SSH command only for servers that the device can reach. The private address is also in the **Addresses** section of the server's **Networking** tab.

## Let a device reach a server

A server accepts no WireGuard traffic until you turn it on:

1. Go to **Servers**. Click the server. Click **Access**.
2. Under **WireGuard**, turn on **WireGuard access**.

When the switch is on, all WireGuard devices of the team in that region can reach the server. Turn it off to block all devices from that server. The switch shows only in regions with a WireGuard gateway.

## What a device can reach

The server firewall does not filter WireGuard devices. You cannot set rules for one device or one member.

The tunnel works both ways. While the tunnel is on, a server that the device can reach can also connect to the device. Keep the firewall of the device on, and turn off the tunnel when you do not need it.

## Delete a device

1. Open the settings and click **WireGuard**.
2. Open the row menu of the device. Click **Delete**.
3. Click **Delete** to confirm.

If the gateway does not answer, the device shows **Removing**. Frappe Cloud tries again every few minutes until it is removed.

## Who can see and do what

| Action | Owner | Admin | Developer | Billing | Viewer |
| --- | :-: | :-: | :-: | :-: | :-: |
| See the team's devices | ✓ | ✓ | ✓ | | |
| Add a device | ✓ | ✓ | ✓ | | |
| Delete your own device | ✓ | ✓ | ✓ | | |
| Delete the device of another member | ✓ | ✓ | | | |
| Turn WireGuard access on or off for a server | ✓ | ✓ | ✓ | | |

- Billing and Viewer do not see the **WireGuard** settings.
- A member sees the name, owner, region, and public key of each device. Nobody can see a private key, because Frappe Cloud never has it. A public key alone cannot connect.
- A role on one server can turn **WireGuard access** on or off for that server. Adding and deleting devices needs a role on **All resources**.
- In a [custom role](/team/roles#create-a-custom-role), **See, add, and remove team WireGuard devices** lets a member manage devices. **Change the firewall, public addresses, and WireGuard access of servers** lets a member change server access.
- A team can have at most 100 devices.

## When a member loses access

Frappe Cloud removes every device of a member when the member can no longer manage WireGuard devices. This happens when:

- The member leaves the team or is removed from it.
- The member gets a role that cannot manage WireGuard devices, such as Viewer.
- The member's account is disabled.
- The team is archived.

A suspended team keeps its devices. Its servers are stopped, so the devices reach nothing until the team is active again.

## See also

- [Networking and firewall](/servers/networking)
- [Connect with SSH](/servers/access)
- [Roles and permissions](/team/roles)
