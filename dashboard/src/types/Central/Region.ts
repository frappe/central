export interface Region {
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
	/**	Region : Data - Region code, e.g. in-mumbai.	*/
	region: string
	/**	Display Name : Data - Human region label shown in the console, e.g. Mumbai, India.	*/
	display_name?: string
	/**	Provider : Select - Infrastructure provider hosting this region, shown as the pin's brand mark. Display vocabulary only — distinct from Atlas's Server.provider_type (DigitalOcean/Scaleway/Self-Managed/Fake); reconcile into a shared source if provider identity ever needs to be authoritative.	*/
	provider?:
		| ''
		| 'AWS'
		| 'Hetzner'
		| 'Frappe'
		| 'OCI'
		| 'DigitalOcean'
		| 'Scaleway'
		| 'Self-Managed'
		| 'Fake'
	/**	Country Code : Data - ISO 3166-1 alpha-2 code, e.g. IN. The console derives the flag emoji from it.	*/
	country_code?: string
	/**	Latitude : Float - Region latitude for the console world map. 0/0 keeps the region off the map (it still lists).	*/
	latitude?: number
	/**	Longitude : Float - Region longitude for the console world map.	*/
	longitude?: number
	/**	Status : Select	*/
	status: 'Active' | 'Draining' | 'Disabled'
	/**	Base URL : Data - Base URL of the regional Atlas, e.g. https://blr.atlas.example.com. Blank until an operator connects this region to one.	*/
	base_url?: string
	/**	Atlas Region ID : Data - Numeric region ID from Atlas Settings, from 0 to 65535. Leave blank until the operator confirms it.	*/
	atlas_region_id?: string
	/**	Proxy Domain : Data - Wildcard zone the regional proxy serves, without the leading *., e.g. par-2.fc.frappe.dev. Leave blank until the operator confirms it; one-click Open stays unavailable until it is set.	*/
	proxy_domain?: string
	/**	Reachable : Check - The last signed Atlas tenant API check succeeded. A generic ping is not sufficient.	*/
	reachable?: 0 | 1
	/**	Connection Checked At : Datetime	*/
	connection_checked_at?: string
	/**	Connection Error : Small Text	*/
	connection_error?: string
	/**	Last Synced At : Datetime	*/
	last_synced_at?: string
	/**	Webhook Secret : Password - Shared secret reserved for signed regional state delivery.	*/
	webhook_secret?: string
	/**	Cargo Status : Select - Registered means the host collected its tokens and is running.	*/
	cargo_status?: 'Draft' | 'Registered' | 'Disabled'
	/**	Cargo Base URL : Data - Where this region's Cargo site is served, e.g. http://10.0.0.5:8000. Recorded when the host enrols.	*/
	cargo_base_url?: string
	/**	Cargo Registered At : Datetime	*/
	cargo_registered_at?: string
	/**	Cargo Webhook Secret : Password - Signs this region's Cargo service reports. Central checks every delivery against it.	*/
	cargo_webhook_secret?: string
}
