
export interface CentralSettings{
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
	/**	Enable Add-ons : Check - Show the Add-ons area (LLM / storage services) in the console. Off hides its nav entry and blocks its routes.	*/
	enable_addons?: 0 | 1
	/**	Enable LLM Service : Check	*/
	enable_llm_service?: 0 | 1
	/**	Enable PDF Print Service : Check	*/
	enable_pdf_print_service?: 0 | 1
	/**	Enable Email Delivery Service : Check	*/
	enable_email_delivery_service?: 0 | 1
	/**	Enable Object Storage Service : Check	*/
	enable_object_storage_service?: 0 | 1
}