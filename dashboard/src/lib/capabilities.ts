import type { CapabilityInfo, CapabilityPlane } from '@/types/api'

// Grouping of capabilities by plane, shared by the capability-transparency panel
// (CapabilityList) and the role builder. The bench plane is deferred today but
// kept here so it groups correctly when site capabilities return.
export const PLANE_LABEL: Record<CapabilityPlane, string> = {
	central: 'Team & billing',
	atlas: 'Servers',
	bench: 'Bench',
}

const PLANE_ORDER: CapabilityPlane[] = ['central', 'atlas', 'bench']

export interface CapabilityGroup {
	plane: CapabilityPlane
	label: string
	caps: CapabilityInfo[]
}

/** Bucket `palette` by plane in canonical order. With `granted`, keep only those
 *  capabilities (the panel view); without it, keep all (the builder view). */
export function groupCapabilitiesByPlane(
	palette: CapabilityInfo[],
	granted?: string[],
): CapabilityGroup[] {
	const allow = granted ? new Set(granted) : null
	const byPlane = new Map<CapabilityPlane, CapabilityInfo[]>()
	for (const cap of palette) {
		if (allow && !allow.has(cap.name)) continue
		const list = byPlane.get(cap.plane) ?? []
		list.push(cap)
		byPlane.set(cap.plane, list)
	}
	return PLANE_ORDER.filter((p) => byPlane.has(p)).map((plane) => ({
		plane,
		label: PLANE_LABEL[plane],
		caps: byPlane.get(plane)!,
	}))
}
