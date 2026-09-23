export type SnapshotType = 'Automatic' | 'Manual' | 'Terminate'
export type SnapshotStatus = 'Pending' | 'Available' | 'Failed'

/** One row of central.api.snapshots.list_snapshots. */
export interface VMSnapshotRow {
	name: string
	title: string
	server: string
	server_title: string
	region: string
	snapshot_type: SnapshotType
	status: SnapshotStatus
	size_mib: number
	size_gib: number
	creation: string
	/** When Central deletes a daily snapshot. Null for any other, and for a kept one. */
	expires_at: string | null
	/** One of its server's newest snapshots within the free count. */
	is_free: boolean
	is_billed: boolean
	/** What it costs per month when billed. Null when the region has no price. */
	monthly_cost: number | null
	is_restorable: boolean
	image_offering: string | null
	atlas_image_id: string | null
	error_detail: string | null
}

export interface SnapshotServerSetting {
	resource_id: string
	/** The owner's switch for this server. */
	automatic: boolean
	/** Whether the region takes daily snapshots at all. */
	region_automatic: boolean
}

export interface SnapshotList {
	snapshots: VMSnapshotRow[]
	currency: string
	/** How many of each server's newest snapshots are free. */
	free_per_server: number
	daily_retention_hours: number
	/** Price per GB-month by region. Null when a region has no Snapshot rate. */
	rates: Record<string, number | null>
	server?: SnapshotServerSetting
}

export interface SnapshotPricing {
	rate_per_gib: number | null
	currency: string
	free_per_server: number
	daily_retention_hours: number
}
