export type RegionInfo = { city: string; label: string; x: number; y: number }

// x/y are fractions of the dotted-map SVG canvas, calibrated by eye against
// the dot grid — the map's projection isn't a clean equirectangular.
const REGIONS: Record<string, RegionInfo> = {
  mumbai: { city: 'Mumbai', label: 'Mumbai, India · AWS', x: 0.726, y: 0.515 },
}

// Unknown regions (e.g. the dev stub's "local-dev") fall back to Mumbai so the
// provisioning screen always renders like the design.
export function regionInfo(slug: string | null | undefined): RegionInfo {
  return REGIONS[(slug ?? '').toLowerCase()] ?? REGIONS.mumbai
}
