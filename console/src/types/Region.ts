import type { AtlasInstance } from './Central/AtlasInstance'

/** Active Atlas Instance rows surfaced by list_instances. */
export type Region = Pick<AtlasInstance, 'region' | 'status' | 'reachable'>
