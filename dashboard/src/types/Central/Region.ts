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
	/**	Region : Data - Region code, e.g. in-mumbai. One Atlas Instance maps to one Region.	*/
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
}
