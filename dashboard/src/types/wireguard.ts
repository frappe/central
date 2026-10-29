/** The fields Central's WireGuard device APIs return. */
export interface WireGuardDevice {
	name: string
	title: string
	region: string
	status: 'Active' | 'Removing'
	added_by: string
	added_by_name?: string
	public_key: string
	address: string
	/** One server range per line. */
	allowed_ips: string
	endpoint: string
	gateway_public_key: string
	creation: string
	/** The viewer added the device or can manage members. */
	can_delete?: boolean
}

export interface WireGuardRegion {
	name: string
	display_name: string | null
}

export interface WireGuardServer {
	resource_id: string
	title: string
	region: string
	ipv6_address: string | null
	has_wireguard_access: 0 | 1
}

/** A device shown in its settings dialog. The private key is set only right after the browser made it. */
export interface OpenedWireGuardDevice {
	device: WireGuardDevice
	privateKey: string
}
