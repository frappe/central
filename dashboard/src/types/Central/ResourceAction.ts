export interface ResourceAction {
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
	/**	Resource Type : Select	*/
	resource_type: 'Server' | 'Site'
	/**	Action : Select	*/
	action: 'create' | 'start' | 'stop' | 'terminate' | 'resize'
	/**	Team : Link - Team	*/
	team: string
	/**	Resource ID : Data - The server (VM id) or site (FQDN) this action targets, snapshotted so the row stays meaningful after the resource is gone.	*/
	resource_id?: string
	/**	Status : Select	*/
	status:
		| 'Queued'
		| 'Sent'
		| 'In Progress'
		| 'Succeeded'
		| 'Failed'
		| 'Timed Out'
	/**	Atlas Task : Data - The Atlas Task this action produced, for operator cross-reference.	*/
	atlas_task?: string
	/**	Completed At : Datetime	*/
	completed_at?: string
	/**	Error Code : Data - Stable error code from the failure envelope (central/errors.py).	*/
	error_code?: string
	/**	Retriable : Check	*/
	retriable?: 0 | 1
	/**	Error Message : Small Text	*/
	error_message?: string
	/**	Remediation : Small Text	*/
	remediation?: string
}
