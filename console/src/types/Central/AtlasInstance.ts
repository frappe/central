
export interface AtlasInstance{
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
	/**	Region : Data - The cluster the user sees. One Atlas = one region.	*/
	region: string
	/**	Base URL : Data - Base URL of the regional Atlas, e.g. https://blr.atlas.example.com	*/
	base_url: string
	/**	Status : Select	*/
	status: "Active" | "Draining" | "Disabled"
	/**	API Key : Data - frappe API key of the Central service user on the Atlas site.	*/
	api_key: string
	/**	API Secret : Password - frappe API secret (stored encrypted). Sent as `token key:secret`.	*/
	api_secret: string
	/**	Reachable : Check	*/
	reachable?: 0 | 1
	/**	Last Synced At : Datetime	*/
	last_synced_at?: string
}