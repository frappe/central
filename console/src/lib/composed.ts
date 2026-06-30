// Pure math for the "design your own" config slider (#84). The server is the gate
// (central.billing … get_eligible_plans / provision_composed_config re-validate
// composition, bounds, and headroom); these helpers just keep the slider on-shape
// and inside headroom so the customer can't drag into a config they can't afford.

import type { ComposedConfig, Profile, RateCard } from '@/types/api'

/** RAM follows vCPU by the profile's ratio — never independently chosen, so an
 *  off-ratio shape can't be expressed. */
export function ramFor(vcpus: number, profile: Profile): number {
  return vcpus * profile.ram_ratio
}

/** Live estimate `Σ(quantity × component_rate)` for a config, in the team's currency. */
export function estimateConfig(config: ComposedConfig, rateCard: RateCard): number {
  return (
    config.vcpus * (rateCard.Compute?.rate ?? 0) +
    config.memory_gb * (rateCard.Memory?.rate ?? 0) +
    config.disk_gb * (rateCard.Disk?.rate ?? 0)
  )
}

/** The largest vCPU rung whose full config (its derived RAM + the chosen disk) still
 *  fits `available` headroom — the slider's hard stop. Falls back to the smallest
 *  rung when even that doesn't fit (the caller then shows the over-headroom state). */
export function maxAffordableVcpu(
  profile: Profile,
  rateCard: RateCard,
  available: number,
  diskGb: number,
): number {
  return largestAffordable(profile.vcpu_steps, (vcpus) =>
    estimateConfig(
      { sub_category: profile.sub_category, vcpus, memory_gb: ramFor(vcpus, profile), disk_gb: diskGb },
      rateCard,
    ),
    available,
  )
}

/** The largest storage rung (from the profile's ladder) that fits the remaining
 *  headroom after the chosen vCPU + RAM are paid for. */
export function maxAffordableDisk(
  profile: Profile,
  rateCard: RateCard,
  available: number,
  vcpus: number,
): number {
  return largestAffordable(profile.disk_steps, (diskGb) =>
    estimateConfig(
      { sub_category: profile.sub_category, vcpus, memory_gb: ramFor(vcpus, profile), disk_gb: diskGb },
      rateCard,
    ),
    available,
  )
}

/** The largest ladder rung whose cost fits `available`; the smallest rung if none do. */
function largestAffordable(ladder: number[], costOf: (rung: number) => number, available: number): number {
  const rungs = [...ladder].sort((a, b) => a - b)
  let best = rungs[0] ?? 0
  for (const rung of rungs) if (costOf(rung) <= available) best = rung
  return best
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/** A vCPU count as the configurator shows it: 1/8 → '⅛', 1/2 → '½', else the number. */
const VCPU_FRACTIONS: Record<string, string> = { '0.125': '⅛', '0.25': '¼', '0.5': '½' }
export function formatVcpu(vcpus: number): string {
  return VCPU_FRACTIONS[String(vcpus)] ?? formatGb(vcpus)
}

/** Trim trailing zeros: 2 → '2', 0.25 → '0.25'. */
export function formatGb(value: number): string {
  return Number.isInteger(value) ? `${value}` : `${value}`.replace(/\.?0+$/, '')
}

/** Compact spec line for a composed config, matching the preset spec style. */
export function configSpecs(config: ComposedConfig): string {
  return `${formatVcpu(config.vcpus)} vCPU · ${formatGb(config.memory_gb)} GB RAM · ${formatGb(config.disk_gb)} GB SSD`
}

/** The composition payload the provision/resize endpoints take (Plan Includes shape). */
export function configIncludes(config: ComposedConfig) {
  return [
    { resource_type: 'Compute', quantity: config.vcpus, unit: 'vCPU' },
    { resource_type: 'Memory', quantity: config.memory_gb, unit: 'GB' },
    { resource_type: 'Disk', quantity: config.disk_gb, unit: 'GB' },
  ]
}

/** Whether a composed config is fully priceable (every component on the rate card). */
export function rateCardComplete(rateCard: RateCard): boolean {
  return !!(rateCard.Compute && rateCard.Memory && rateCard.Disk)
}
