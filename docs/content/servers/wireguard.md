---
title: WireGuard VPN
description: Connect a laptop or phone to your servers over their private addresses with WireGuard VPN, and see which roles can do what.
---

# WireGuard VPN

WireGuard VPN connects a device to your servers through an encrypted tunnel. A device is a laptop, phone, or other computer that reaches your servers over their private IPv6 addresses. The traffic goes through an encrypted tunnel to the WireGuard gateway of the region. The servers do not need a public address or an open SSH port.

A device belongs to the team and to one region. It reaches only the servers of your team in that region that have **WireGuard VPN** on.

WireGuard VPN is available only in regions that have a WireGuard VPN gateway. If no region has one, the **WireGuard VPN** settings show that it is not available yet.

## Add a device

1. Click your name at the bottom of the sidebar, then **Settings**. In the settings, under **Access**, click **WireGuard VPN**. You can also press `Ctrl+,` or `⌘+,` to open the settings.
2. Click **Add**. If the team has no devices yet, click **Add device**.
3. Type a **Name**, such as `Work laptop`.
4. Select the **Region**.
5. Click **Add device**.

Your browser makes the key pair. Only the public key goes to Frappe Cloud. The dialog then shows a QR code and a **Download .conf** button. Both hold the private key. Scan the code on a phone, or download the file on a computer. The file has the name of the device, such as `work-laptop.conf`.

::: warning
The QR code and the file with the private key show only once. If you lose the file, delete the device and add it again.
:::

A device reaches a server only after you turn on [WireGuard VPN](#let-a-device-reach-a-server) for that server. Before you connect the device, [protect it](#protect-the-device).

### Use your own key pair

To keep the private key off the browser, make the key pair yourself:

```bash
umask 077
wg genkey > private.key
wg pubkey < private.key
```

`umask 077` keeps the private key readable by you alone.

In the dialog, select **I have my own key pair** and paste the public key. Never paste the private key.

The dialog then shows a **Download .conf** button. The file has `<your private key>` in place of the key. Put your private key there before you import it. To download the file again later, open the row menu of the device and click **Download .conf**.

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

1. In the **WireGuard VPN** settings, go to **Servers**.
2. Click the SSH command of a server to copy it.
3. Run the command:

   ```bash
   ssh root@2001:db8:4a:6::10
   ```

   **Servers** shows the SSH command only for servers that have WireGuard VPN on. The private address is also in the **Addresses** section of the server's **Networking** tab.

## Let a device reach a server

A server accepts no WireGuard VPN traffic until you turn it on. Use one of these switches:

- In the **WireGuard VPN** settings, under **Servers**, turn on the switch of the server.
- Go to **Servers**. Click the server. Click **Access**. Turn on **WireGuard VPN**.

When the switch is on, the server heading shows a **VPN** tag. Turn it off to block all devices from that server. The switch shows only in regions with a WireGuard VPN gateway.

If the firewall of the server is on, it must also allow the device:

1. Go to the **Networking** tab of the server.
2. In **Firewall**, add an incoming rule, such as **SSH**.
3. Select **Specific addresses**, then select the device by its name. Press Enter.
4. Click **Apply changes**.

When the switch is on but the firewall allows no device, the **Access** tab and the **Servers** list show **The firewall blocks every device**.

## What a device can reach

A device reaches a server only when the WireGuard VPN switch of the server is on and the firewall allows the device. A firewall rule names one device by its address, so you can allow one device and not another, and allow it only on some ports.

If a region restore gives a device a new address, a rule with the old address no longer matches. Update the rule with the new address.

The tunnel works both ways. See [Protect the device](#protect-the-device).

## Protect the device

The tunnel connects in both directions, like a site-to-site link. While the tunnel is on, each server of your team in the region that has WireGuard VPN on can open a connection to the device. The server can reach every open port on the tunnel address of the device, such as `fdac:1:1:0:4::1`. Frappe Cloud does not filter this traffic.

::: warning
If an attacker gets into one of these servers, they can use the tunnel to connect to services on the device. Block incoming traffic from the tunnel on the device.
:::

The risk is highest for a device that stays connected, such as:

- An application server or another cloud server that connects to a database on Frappe Cloud.
- A CI runner, a backup host, or a monitoring host.
- An office computer that keeps the tunnel on.

A laptop that you connect for a short time has less risk. It still needs a firewall.

### What to do

1. Turn on the firewall of the device. Block incoming connections from the tunnel by default. Replies to connections that the device starts still work.
2. Allow only the ports that your servers must reach. Allow them only on the tunnel interface.
3. Bind each service on the device to `localhost` or to one address, unless the servers must reach it.
4. Turn off the tunnel when you do not use it.
5. Add a separate device for each machine. Delete a device when you no longer need it.

### Example: Linux with ufw

The tunnel interface has the name of the file without `.conf`, such as `work-laptop`.

If you sign in to the machine over SSH, allow SSH first, or `ufw` locks you out:

```bash
sudo ufw allow OpenSSH
```

Block incoming connections by default, then turn on the firewall:

```bash
sudo ufw default deny incoming
sudo ufw enable
```

To let your servers reach one port, allow it on the tunnel interface only. This example allows PostgreSQL on port `5432`:

```bash
sudo ufw allow in on work-laptop to any port 5432 proto tcp
```

On macOS and Windows, turn on the built-in firewall. Block incoming connections for apps that do not need them.

## Delete a device

1. Open the settings and click **WireGuard VPN**.
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
| Turn WireGuard VPN on or off for a server | ✓ | ✓ | ✓ | | |

- Billing and Viewer do not see the **WireGuard VPN** settings.
- A member sees the name, owner, region, and public key of each device. Nobody can see a private key, because Frappe Cloud never has it. A public key alone cannot connect.
- A role on one server can turn **WireGuard VPN** on or off for that server. Adding and deleting devices needs a role on **All resources**.
- In a [custom role](/team/roles#create-a-custom-role), **See, add, and remove team WireGuard devices** lets a member manage devices. **Change the firewall, public addresses, and WireGuard access of servers** lets a member change server access.
- A team can have at most 100 devices.

## When a member loses access

Frappe Cloud removes every device of a member when the member can no longer manage WireGuard VPN devices. This happens when:

- The member leaves the team or is removed from it.
- The member gets a role that cannot manage WireGuard VPN devices, such as Viewer.
- The member's account is disabled.
- The team is archived.

A suspended team keeps its devices. Its servers are stopped, so the devices reach nothing until the team is active again.

## See also

- [Networking and firewall](/servers/networking)
- [Connect with SSH](/servers/access)
- [Roles and permissions](/team/roles)
