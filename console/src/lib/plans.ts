// Size presets for the New Server flow. Plans/sizes aren't modeled on Central
// yet (Atlas pulls a size catalog from Central, but that catalog doesn't exist
// here), so these are front-end presets passed straight to create_server as
// raw resources. When Central grows a real Size/Plan doctype, swap this constant
// for a fetch — the shape (vcpus/memory/disk) already matches what the API takes.

export interface SizePreset {
  slug: string
  label: string
  vcpus: number
  /** Fractional CPU bandwidth share for sub-1-vCPU sizes; omit to default to vcpus. */
  cpuMaxCores?: number
  memoryMegabytes: number
  diskGigabytes: number
}

export const SIZE_PRESETS: SizePreset[] = [
  { slug: 'hobby', label: 'Hobby', vcpus: 1, cpuMaxCores: 0.5, memoryMegabytes: 512, diskGigabytes: 10 },
  { slug: 'starter', label: 'Starter', vcpus: 1, memoryMegabytes: 1024, diskGigabytes: 20 },
  { slug: 'standard', label: 'Standard', vcpus: 2, memoryMegabytes: 2048, diskGigabytes: 40 },
  { slug: 'business', label: 'Business', vcpus: 4, memoryMegabytes: 8192, diskGigabytes: 80 },
]

/** Compact spec line for a preset card, e.g. "2 vCPU · 2 GB RAM · 40 GB". */
export function presetSpecs(p: SizePreset): string {
  const gb = p.memoryMegabytes >= 1024 ? `${p.memoryMegabytes / 1024} GB` : `${p.memoryMegabytes} MB`
  return `${p.vcpus} vCPU · ${gb} RAM · ${p.diskGigabytes} GB`
}
