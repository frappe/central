import type { Region } from '@/types/Region'

export type StorageRegion = Pick<
	Region,
	| 'region'
	| 'display_name'
	| 'provider'
	| 'country_code'
	| 'latitude'
	| 'longitude'
>

export interface StorageBucket {
	name: string
	bucket_name: string
	region: string
	status: 'Active' | 'Suspended'
	endpoint_url: string
	access_key: string
	creation: string
	is_managed: boolean
}

export interface BucketCredentials {
	name: string
	bucket_name: string
	region: string
	endpoint_url: string
	access_key: string
	secret_access_key: string
}

export interface BucketUsage {
	used_bytes: number
	object_count: number
	quota_bytes: number | null
	quota_objects: number | null
}

export interface ObjectStorage {
	regions: StorageRegion[]
	buckets: StorageBucket[]
}
