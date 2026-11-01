export interface ImageOffering {
	name: string
	title: string
	logo: string | null
	description: string | null
}

export interface RegionalImage {
	id: string
	title: string
	architecture: string
	rootfs_size_mib: number
	/** Unix seconds. Two builds of one version differ by this and little else. */
	created_at: number
	tags: Record<string, string>
}

/** A ready-to-run application the region's Cargo has built an image of. */
export interface Template {
	application: string
	title: string
	os_version: string | null
	information: string | null
	snapshot_id: string
}

export interface TemplateInput {
	name: string
	label: string
	type: 'string' | 'email' | 'domain' | 'password'
	required?: boolean
	description?: string
	/** A blank answer gets a generated value at first boot. */
	generate?: boolean
}

export interface TemplateRequirements {
	inputs: TemplateInput[]
	minimum_size: { cpu_millicores: number; memory_mib: number; disk_mib: number }
	ports: { port: number; protocol: string }[]
}

export interface ImageSelection {
	offering: string
	image_id: string
	/** A restore names the VM Snapshot; Central reads its offering and image from it. */
	snapshot?: string
}

export interface ActionStatus {
	action: string
	status:
		| 'Queued'
		| 'Dispatching'
		| 'Sent'
		| 'In Progress'
		| 'Succeeded'
		| 'Failed'
		| 'Uncertain'
		| 'Timed Out'
	resource_id: string | null
	title: string
	error: {
		code: string
		title: string
		message: string
		remediation: string
		retriable: boolean
	} | null
}
