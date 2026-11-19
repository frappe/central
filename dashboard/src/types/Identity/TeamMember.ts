export interface TeamMember {
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
	/**	User : Link - User	*/
	user: string
	/**	Role : Link - Team Role	*/
	role: string
	/**	Resource Type : Select	*/
	resource_type: '*' | 'Server' | 'Site'
	/**	Resource Name : Data	*/
	resource_name?: string
	/**	Status : Select	*/
	status: 'Active' | 'Invited' | 'Suspended'
}
