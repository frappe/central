// Mirrors the Atlas Instance doctype MINUS its secret fields (base_url,
// api_key, api_secret, tunnel/peer internals). The console only ever receives
// list_instances' INSTANCE_PUBLIC_FIELDS allowlist — keep the pruning if this
// file is ever regenerated from the doctype.
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
	/**	Status : Select	*/
	status: "Active" | "Draining" | "Disabled"
	/**	Display Name : Data - Human region label shown in the console, e.g. Mumbai, India.	*/
	display_name?: string
	/**	Provider : Select - Infrastructure provider hosting this region, shown as the pin's brand mark.	*/
	provider?: "" | "AWS" | "Hetzner" | "Frappe" | "OCI" | "DigitalOcean"
	/**	Country Code : Data - ISO 3166-1 alpha-2 code, e.g. IN. The console derives the flag emoji from it.	*/
	country_code?: string
	/**	Latitude : Float - Region latitude for the console's world map. 0/0 means "not placed".	*/
	latitude?: number
	/**	Longitude : Float - Region longitude for the console's world map.	*/
	longitude?: number
	/**	Reachable : Check	*/
	reachable?: 0 | 1
	/**	Last Synced At : Datetime	*/
	last_synced_at?: string
}
