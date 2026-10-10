export interface TeamOnboardingStep {
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
	/**	Step : Select	*/
	step: 'invite' | 'billing' | 'start'
	/**	Status : Select	*/
	status: 'Pending' | 'Done' | 'Skipped'
	/**	Updated By : Link - User	*/
	updated_by?: string
	/**	Updated On : Datetime	*/
	updated_on?: string
}
