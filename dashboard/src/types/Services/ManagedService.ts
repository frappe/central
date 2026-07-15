
export interface ManagedService{
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
	/**	Team : Link - Team	*/
	team: string
	/**	Add-on Service : Link - Add-on Service	*/
	add_on_service: string
	/**	Subscription : Link - Subscription	*/
	subscription: string
	/**	Status : Select	*/
	status?: "Draft" | "Provisioning" | "Active" | "Failed" | "Suspended"
	/**	Provider Reference : Data	*/
	provider_ref?: string
}