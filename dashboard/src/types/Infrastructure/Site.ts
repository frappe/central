export interface Site {
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
	/**	Site Name : Data - The site's public address, which is also its name. The regional proxy derives it from the machine, so it is settled the moment the machine has one.	*/
	site_name: string
	/**	Subdomain : Data - The single label the customer named this site. Their address is this label in the machine's own zone; the site's own name stays ours.	*/
	subdomain?: string
	/**	Team : Link - Team - The team that owns this site.	*/
	team: string
	/**	Product : Link - Product - The product the customer signed up for. Empty for a plain trial.	*/
	product?: string
	/**	Server : Link - Virtual Machine - The machine this site runs on. A site has no state of its own: its status, region and size are all the machine's.	*/
	server: string
	/**	Ready At : Datetime - The first time Central confirmed that the site answered on its public address.	*/
	ready_at?: string
	/**	Claimed At : Datetime - The first time Central created a working login handoff for this site.	*/
	claimed_at?: string
	/**	Rename Task : Data - The Pilot task that renamed the bench site onto the customer's subdomain. Set once, when the rename is sent; empty means it never was.	*/
	rename_task?: string
	/**	Rename Error : Small Text - A safe summary of the latest site rename failure.	*/
	rename_error?: string
	/**	Rename Diagnostic : Code - The traceback of the latest site rename failure. Operators only.	*/
	rename_diagnostic?: string
	/**	Trial State : Select - Active runs free until the end date. Ended means the server is stopped and is terminated on the deletion date. Converted means the team added a payment method. Deleted means the trial ended without one. Empty for a site that is not a trial.	*/
	trial_state?: '' | 'Active' | 'Ended' | 'Converted' | 'Deleted'
	/**	Trial Ends On : Date - The day the trial ends and its server stops.	*/
	trial_ends_on?: string
	/**	Trial Deletes On : Date - The day an ended trial's server is terminated.	*/
	trial_deletes_on?: string
	/**	Trial Last Notice : Data - The last trial email sent for this site, so the daily job sends each one once.	*/
	trial_last_notice?: string
	/**	Trial Cost : Currency - What the free trial cost: the plan's monthly rate for the days the trial ran. Set when the trial converts or is deleted.	*/
	trial_cost?: number
	/**	Trial Currency : Link - Currency	*/
	trial_currency?: string
	/**	Trial Error : Small Text - Why the daily trial job could not stop or terminate the server. It retries the next day.	*/
	trial_error?: string
}
