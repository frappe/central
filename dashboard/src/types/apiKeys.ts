export type ApiKeyAccess = 'Read' | 'Write'

/** A key of the signed-in user. The secret never comes back after creation. */
export interface ApiKey {
	name: string
	title: string
	team: string
	enabled: boolean
	expires_at: string
	last_used_at: string | null
	creation: string
	/** The first characters of the public key, to tell keys apart. */
	key_prefix: string
	scopes: Record<string, ApiKeyAccess>
}

export interface ApiKeyList {
	keys: ApiKey[]
	/** Each category and the levels a key can take in it. */
	scopes: Record<string, ApiKeyAccess[]>
	expiry_days: number[]
}

export interface NewApiKey {
	team: string
	title: string
	expires_in_days: number
	scopes: Record<string, ApiKeyAccess>
}
