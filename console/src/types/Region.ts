import type { AtlasInstance } from './Central/AtlasInstance'

/** Active Atlas Instance rows surfaced by list_instances (its INSTANCE_PUBLIC_FIELDS allowlist). */
export type Region = Pick<
  AtlasInstance,
  | 'region'
  | 'status'
  | 'reachable'
  | 'display_name'
  | 'provider'
  | 'country_code'
  | 'latitude'
  | 'longitude'
>
