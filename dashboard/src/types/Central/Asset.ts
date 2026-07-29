export interface Asset {
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
	/**	Resource ID : Data - The VM identifier in Atlas (the source of truth).	*/
	resource_id: string
	/**	Title : Data - Human label. Central-created servers retain the user-provided name; discovered servers use the Atlas VM title (resource_id is a UUID).	*/
	title?: string
	/**	Team : Link - Team - Owning Central team (mirrored from Atlas).	*/
	team: string
	/**	Cluster : Link - Atlas Instance - The cluster (Atlas Instance / region) this VM lives in.	*/
	cluster: string
	/**	Plan : Link - Plan	*/
	plan?: string
	/**	Frappe Version : Data - Frappe version the VM was provisioned with — requested at create, resolved to a bench image and echoed back by Atlas (an unbuilt version falls back to the default).	*/
	frappe_version?: string
	/**	Status : Select - Mirrors the Atlas-reported status verbatim (raw VM, or Site/Pilot front-door status for bench/site VMs).	*/
	status?:
		| 'Pending'
		| 'Provisioning'
		| 'Deploying'
		| 'Running'
		| 'Paused'
		| 'Stopped'
		| 'Failed'
		| 'Terminated'
	/**	vCPUs : Int	*/
	vcpus?: number
	/**	Memory (MB) : Int	*/
	memory_megabytes?: number
	/**	Disk (GB) : Int	*/
	disk_gigabytes?: number
	/**	IPv6 Address : Data	*/
	ipv6_address?: string
	/**	Public IPv4 : Data	*/
	public_ipv4?: string
	/**	Gateway URL : Data - The URL a bench VM is fronted at, reported by Atlas; empty for a non-bench VM.	*/
	gateway_url?: string
	/**	Login URL : Small Text - One-click admin sign-in URL Atlas minted after boot; short-lived, regenerated on expiry.	*/
	login_url?: string
	/**	Login URL Expires At : Datetime - When login_url stops working (Atlas mint time + token TTL).	*/
	login_url_expires_at?: string
	/**	Resize In Progress : Check - Set while a background hardware resize runs; blocks power actions and shows a Resizing state.	*/
	resize_in_progress?: 0 | 1
	/**	Last Synced At : Datetime - When the last reconcile (pull) refreshed this row.	*/
	last_synced_at?: string
	/**	Last Event At : Datetime - occurred_at of the last applied Atlas event; drives last-writer-wins.	*/
	last_event_at?: string
}
