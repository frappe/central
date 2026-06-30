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

/** The largest vCPU step whose full config (its derived RAM + the chosen disk) still
 *  fits `available` headroom — the slider's hard stop. Falls back to the smallest
 *  step when even that doesn't fit (the caller then shows the over-headroom state). */
export function maxAffordableVcpu(
  profile: Profile,
  rateCard: RateCard,
  available: number,
  diskGb: number,
): number {
  const steps = [...profile.vcpu_steps].sort((a, b) => a - b)
  let best = steps[0] ?? 0
  for (const step of steps) {
    const cost = estimateConfig(
      { sub_category: profile.sub_category, vcpus: step, memory_gb: ramFor(step, profile), disk_gb: diskGb },
      rateCard,
    )
    if (cost <= available) best = step
  }
  return best
}

/** The largest disk (GB) that fits both the profile's range and the remaining
 *  headroom after the chosen vCPU + RAM are paid for. */
export function maxAffordableDisk(
  profile: Profile,
  rateCard: RateCard,
  available: number,
  vcpus: number,
): number {
  const diskRate = rateCard.Disk?.rate ?? 0
  const spentOnCompute = estimateConfig(
    { sub_category: profile.sub_category, vcpus, memory_gb: ramFor(vcpus, profile), disk_gb: 0 },
    rateCard,
  )
  const headroomDisk = diskRate > 0 ? Math.floor((available - spentOnCompute) / diskRate) : profile.disk_max
  return clamp(Math.min(profile.disk_max, headroomDisk), profile.disk_min, profile.disk_max)
}

/** Snap a raw slider value to the nearest allowed vCPU step. */
export function snapVcpu(value: number, steps: number[]): number {
  if (!steps.length) return value
  return steps.reduce((nearest, step) => (Math.abs(step - value) < Math.abs(nearest - value) ? step : nearest))
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/** Compact spec line for a composed config, matching the preset spec style. */
export function configSpecs(config: ComposedConfig): string {
  return `${config.vcpus} vCPU · ${config.memory_gb} GB RAM · ${config.disk_gb} GB disk`
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
