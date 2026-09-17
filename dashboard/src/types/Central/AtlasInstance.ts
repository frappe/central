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
	/**	Status : Select	*/
	status: 'Active' | 'Draining' | 'Disabled'
	/**	Atlas Region ID : Data - Numeric region ID from Atlas Settings, from 0 to 65535. Leave blank until the operator confirms it.	*/
	atlas_region_id?: string
	/**	Base URL : Data - Base URL of the regional Atlas, e.g. https://blr.atlas.example.com	*/
	base_url: string
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
}
