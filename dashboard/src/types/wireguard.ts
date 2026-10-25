/** The fields Central's WireGuard device APIs return. */
export interface WireGuardDevice {
	name: string
	title: string
	region: string
	status: 'Active' | 'Removing'
	added_by: string
	public_key: string
	address: string
	/** One server range per line. */
	allowed_ips: string
	endpoint: string
	gateway_public_key: string
	creation: string
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
