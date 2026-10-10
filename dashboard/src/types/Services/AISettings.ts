export interface AISettings {
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
	/**	Grove URL : Data - The Grove site that serves AI, e.g. https://grove.frappe.cloud. Teams are registered there as Grove users named by their team id.	*/
	base_url?: string
	/**	Control API Key : Data	*/
	control_api_key?: string
	/**	Control API Secret : Password	*/
	control_api_secret?: string
}
