export interface IAMPermissionProbe {
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
	/**	Team : Link - Team	*/
	team: string
	/**	Capability : Link - Capability	*/
	capability: string
	/**	Allowed : Check	*/
	allowed?: 0 | 1
	/**	Last Checked At : Datetime	*/
	last_checked_at?: string
	/**	Resolved Grants : Code	*/
	resolved_grants?: string
}
