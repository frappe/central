
export interface Asset{
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
	/**	Title : Data - Human label, mirrored from the Atlas VM (resource_id is a UUID).	*/
	title?: string
	/**	Team : Link - Team - Owning Central team (mirrored from Atlas).	*/
	team: string
	/**	Cluster : Link - Atlas Instance - The cluster (Atlas Instance / region) this VM lives in.	*/
	cluster: string
	/**	Status : Select - Mirrors the Atlas Virtual Machine status verbatim.	*/
	status?: "Pending" | "Running" | "Paused" | "Stopped" | "Failed" | "Terminated"
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
	/**	Gateway URL : Data - The bench gateway Central deep-links into (VM leaf). Reserved — empty until the bench-gateway layer reports it.	*/
	gateway_url?: string
	/**	Last Synced At : Datetime - When the last reconcile (pull) refreshed this row.	*/
	last_synced_at?: string
	/**	Last Event At : Datetime - occurred_at of the last applied Atlas event. Used for last-writer-wins so a stale or duplicate push can't overwrite newer state.	*/
	last_event_at?: string
}