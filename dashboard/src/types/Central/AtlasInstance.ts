export interface AtlasInstance {
	name: string
	creation: string
	modified: string
	owner: string
	modified_by: string
	docstatus: 0 | 1 | 2
	parent?: string
	parentfield?: string
	parenttype?: string
	idx?: number
	/**	Region : Link - Region - The cluster the user sees. One Atlas = one Region (joined by this code).	*/
	region: string
	/**	Base URL : Data - Base URL of the regional Atlas, e.g. https://blr.atlas.example.com	*/
	base_url: string
	/**	Status : Select	*/
	status: 'Active' | 'Draining' | 'Disabled'
	/**	Validate Capacity : Check - Only offer plans that fit this region's live capacity when creating or resizing a server (checked against the Atlas capacity API). Off = show the full priced menu and let placement's create-time gate have the final say.	*/
	validate_capacity?: 0 | 1
	/**	Admin API Key : Data - Atlas admin API key. Central authenticates with the Atlas admin token for every Central→Atlas call (the registration handshake and, once Active, the data path over the tunnel).	*/
	api_key: string
	/**	Admin API Secret : Password - Atlas admin API secret, paired with the key (stored encrypted).	*/
	api_secret: string
	/**	Skip Tunnel (Local Dev) : Check - Local development only: register without a WireGuard tunnel. Central does the identity half (scoped service user, pushed creds) and leaves the data path on the public base_url. No hub peering, no firewall lockdown.	*/
	skip_tunnel?: 0 | 1
	/**	Tunnel Status : Select - Unregistered → Provisioning (wg0 up, firewall armed) → Active (confirmed over the tunnel). Inactive = still registered (keeps the service user) but the tunnel has been stripped down; Register again to bring it back up.	*/
	tunnel_status?: 'Unregistered' | 'Provisioning' | 'Active' | 'Inactive'
	/**	Tunnel IP : Data - This Atlas's /32 on wg0, allocated from the pool, e.g. 10.88.0.2. Unique — the hard backstop against a double-allocation race.	*/
	tunnel_ip?: string
	/**	Tunnel URL : Data - Derived from tunnel_ip (e.g. https://10.88.0.2). The post-registration data path; base_url is used only during bootstrap.	*/
	tunnel_url?: string
	/**	Service User : Link - User - The per-Atlas scoped Central service user this Atlas authenticates as when it reports events.	*/
	service_user?: string
	/**	Peer Public Key : Small Text - The Atlas's WireGuard public key, returned by provision_tunnel and added to the hub as a peer.	*/
	peer_public_key?: string
	/**	Peer Endpoint : Data - The Atlas's public wg endpoint (host of base_url : listen port) the hub dials.	*/
	peer_endpoint?: string
	/**	Reachable : Check - Result of the last Test Connection (over the current data path — base_url before/after the tunnel, tunnel_url while Active).	*/
	reachable?: 0 | 1
	/**	Last Synced At : Datetime	*/
	last_synced_at?: string
}
