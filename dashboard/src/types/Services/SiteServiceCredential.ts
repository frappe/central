
export interface SiteServiceCredential{
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
	/**	Managed Service : Link - Managed Service	*/
	managed_service: string
	/**	Site : Link - Site	*/
	site?: string
	/**	Status : Select	*/
	status?: "Active" | "Revoked" | "Failed"
	/**	Gateway URL : Data	*/
	gateway_url?: string
	/**	Provider Reference : Data	*/
	provider_ref?: string
	/**	Last Usage Total : Float	*/
	last_usage_total?: number
	/**	API Key : Password	*/
	api_key?: string
}