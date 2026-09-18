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

export interface ImageSelection {
	offering: string
	image_id: string
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
