export interface AddOnService {
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
	/**	Service Key : Data	*/
	service_key: string
	/**	Title : Data	*/
	title: string
	/**	Handler Key : Data	*/
	handler_key: string
	/**	Plan Category : Link - Plan Category	*/
	plan_category: string
	/**	Is Active : Check	*/
	is_active?: 0 | 1
}
