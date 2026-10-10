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
	/**	Title : Data	*/
	title?: string
	/**	Resource Type : Select	*/
	resource_type: 'Server' | 'Site'
	/**	Action : Select	*/
	action: 'create' | 'start' | 'stop' | 'restart' | 'terminate' | 'resize'
	/**	Team : Link - Team	*/
	team: string
	/**	Region : Link - Region	*/
	region?: string
	/**	Server : Link - Virtual Machine	*/
	server?: string
	/**	Resource ID : Data - Central resource identifier. The regional VM ID is recorded separately.	*/
	resource_id?: string
	/**	Subdomain : Data - The single label the customer named their site. Held here because the site it will name does not exist until the region builds its machine.	*/
	subdomain?: string
	/**	Product : Link - Product - The product this trial starts, used to resume the correct product signup.	*/
	product?: string
	/**	Status : Select	*/
	status:
		| 'Queued'
		| 'Dispatching'
		| 'Sent'
		| 'In Progress'
		| 'Succeeded'
		| 'Failed'
		| 'Uncertain'
		| 'Timed Out'
	/**	Requested By : Link - User	*/
	requested_by?: string
	/**	Dispatched At : Datetime	*/
	dispatched_at?: string
	/**	Last Checked At : Datetime	*/
	last_checked_at?: string
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
	/**	Validated Request : JSON - Validated operation inputs. Contains no credentials or tokens.	*/
	request_payload?: unknown
	/**	Reserved Monthly Rate : Currency	*/
	reserved_monthly_rate?: number
	/**	Atlas VM ID : Data	*/
	remote_vm_id?: string
	/**	Take Snapshot : Check - A terminate that takes a final snapshot first. The server is not destroyed unless the snapshot is Available.	*/
	take_snapshot?: 0 | 1
	/**	VM Snapshot : Link - VM Snapshot	*/
	vm_snapshot?: string
	/**	Correlation ID : Data - Stable Central action identifier for logs and support.	*/
	correlation_id: string
	/**	Request Key : Data - A repeated request in the same Team returns this action instead of dispatching again.	*/
	request_key?: string
	/**	Request Digest : Data	*/
	request_digest?: string
	/**	Pilot Credential : Link - Pilot Credential	*/
	credential?: string
	/**	Error Log : Link - Error Log - Latest Error Log created for this action. All related Error Logs also reference this Resource Action.	*/
	error_log?: string
}
