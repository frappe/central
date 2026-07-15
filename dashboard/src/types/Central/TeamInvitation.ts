export interface TeamInvitation {
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
	/**	Email : Data	*/
	email: string
	/**	Team Role : Link - Team Role	*/
	role: string
	/**	Status : Select	*/
	status?: 'Pending' | 'Accepted' | 'Expired' | 'Revoked'
	/**	Invited By : Link - User	*/
	invited_by?: string
	/**	Expires On : Date	*/
	expires_on?: string
	/**	Accepted By : Link - User	*/
	accepted_by?: string
	/**	Accepted At : Datetime	*/
	accepted_at?: string
}
