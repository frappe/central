import { TeamMember } from './TeamMember'

export interface Team {
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
	/**	Naming Series : Select	*/
	naming_series: 'TEAM-.#####'
	/**	Team Name : Data	*/
	team_name: string
	/**	Owner User : Link - User	*/
	owner_user: string
	/**	Status : Select	*/
	status: 'Active' | 'Suspended'
	/**	Members : Table - Team Member	*/
	members?: TeamMember[]
}
