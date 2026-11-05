export interface ProductEmailNote {
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
	event_type:
		| 'site_ready'
		| 'trial_unopened'
		| 'trial_expiring'
		| 'trial_ended'
		| 'trial_deletion_soon'
		| 'trial_converted'
	note: string
}
