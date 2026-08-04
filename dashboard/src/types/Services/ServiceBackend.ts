export interface ServiceBackend {
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
	/**	Service : Link - Add-on Service	*/
	service: string
	/**	Region : Data	*/
	region?: string
	/**	Base URL : Data	*/
	base_url: string
	/**	Is Active : Check	*/
	is_active?: 0 | 1
	/**	Control API Key : Data	*/
	control_api_key: string
	/**	Control API Secret : Password	*/
	control_api_secret: string
}
