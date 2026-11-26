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
	| 'display_name'
	| 'provider'
	| 'country_code'
	| 'latitude'
	| 'longitude'
> & {
	/** The API sends a boolean, not the doctype's 0 or 1. */
	reachable: boolean
}
