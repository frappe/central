import { ServerSSHKey } from './ServerSSHKey'

export interface VirtualMachine {
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
	/**	Region : Link - Region - The region this VM lives in.	*/
	region: string
	/**	Plan : Link - Plan	*/
	plan?: string
	/**	Atlas VM ID : Data - VM identifier within the linked Atlas region.	*/
	atlas_vm_id?: string
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
	/**	Disk (GB) : Float	*/
	disk_gigabytes?: number
	/**	Image Offering : Link - Image Offering	*/
	image_offering?: string
	/**	Skip Automatic Snapshot : Check - The customer turned off the daily free snapshot for this server.	*/
	skip_automatic_snapshot?: 0 | 1
	/**	Mesh IPv6 : Data - The private WireGuard mesh address. Only the region reaches it.	*/
	ipv6_address?: string
	/**	Public IPv4 : Data	*/
	public_ipv4?: string
	/**	Public IPv6 : Data - The public IPv6 address Atlas reports for the guest.	*/
	public_ipv6?: string
	/**	Gateway URL : Data - The URL a bench VM is fronted at, reported by Atlas; empty for a non-bench VM.	*/
	gateway_url?: string
	/**	Public IPv6 Requested : Check - The customer asked for a public IPv6 address at creation. Anyone on the internet can reach the machine at that address.	*/
	has_public_ipv6?: 0 | 1
	/**	Firewall Enabled : Check - The customer turned on the Atlas firewall at creation. It allows the mesh, ICMP, SSH, HTTP, and HTTPS.	*/
	is_firewall_enabled?: 0 | 1
	/**	SSH Keys : Table - Server SSH Key - Team public keys selected for this server.	*/
	ssh_keys?: ServerSSHKey[]
	/**	Admin Domain Task : Data - The Pilot task that changed the local admin domain to the routed gateway hostname.	*/
	admin_domain_task?: string
	/**	Admin Domain Error : Small Text - A safe summary of the latest admin hostname failure.	*/
	admin_domain_error?: string
	/**	Admin Domain Error Log : Link - Error Log - The Error Log for the latest admin hostname failure.	*/
	admin_domain_error_log?: string
	/**	Atlas Image ID : Data	*/
	atlas_image_id?: string
	/**	State Observed At : Datetime - When Central last recorded this server's state.	*/
	state_observed_at?: string
	/**	Last Reported At : Datetime - The region's observed_at of the last applied report; a report that is not newer is ignored.	*/
	last_reported_at?: string
}
