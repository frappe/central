import { RoleCapability } from './RoleCapability'

export interface TeamRole{
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
	/**	Role Name : Data	*/
	role_name: string
	/**	Is System : Check	*/
	is_system?: 0 | 1
	/**	Team : Link - Team	*/
	team?: string
	/**	Capabilities : Table - Role Capability	*/
	capabilities: RoleCapability[]
}