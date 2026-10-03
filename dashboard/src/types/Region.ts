import type { Region as RegionDoc } from './Central/Region'

/**
 * A placeable region as `central.api.servers.list_instances` returns it: the
 * non-secret fields of an Active Region. Field definitions live on the
 * generated doctype type — change them there, not here.
 */
export type Region = Pick<
	RegionDoc,
	| 'region'
	| 'status'
	| 'reachable'
	| 'display_name'
	| 'provider'
	| 'country_code'
	| 'latitude'
	| 'longitude'
>
