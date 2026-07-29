import type { AtlasInstance } from './Central/AtlasInstance'
import type { Region as RegionDoc } from './Central/Region'

/**
 * A placeable region as `central.api.servers.list_instances` returns it: the
 * Region doctype merged with its Active Atlas Instance's liveness. Region field
 * definitions live on the generated doctype type — change them there, not here.
 */
export type Region = RegionDoc & Pick<AtlasInstance, 'status' | 'reachable'>
