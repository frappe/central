export interface LLMModel {
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
	/**	Model Key : Data	*/
	model_key: string
	/**	Display Name : Data	*/
	display_name?: string
	/**	Tier : Select	*/
	tier?: 'Fast' | 'Balanced' | 'Premium'
	/**	Is Published : Check	*/
	is_published?: 0 | 1
}
