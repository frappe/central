import { capitalise } from '@/lib/format'
import type { CapabilityInfo } from '@/types/api'

// Display-only grouping by capability prefix; the slugs sent to the backend are
// unchanged.
const CATEGORY_LABEL: Record<string, string> = {
	billing: 'Billing',
	team: 'Team',
	service: 'Services',
	server: 'Servers',
	cluster: 'Servers',
}
const CATEGORY_ORDER = ['Billing', 'Team', 'Services', 'Servers']

export interface CapabilityCategory {
	label: string
	caps: CapabilityInfo[]
}

/** Bucket `palette` by capability prefix (billing / team / services / servers).
 *  Unknown prefixes get their own bucket after the known ones. */
export function groupCapabilitiesByCategory(
	palette: CapabilityInfo[],
): CapabilityCategory[] {
	const byLabel = new Map<string, CapabilityInfo[]>()
	for (const cap of palette) {
		const prefix = cap.name.split(':')[0]
		const label = CATEGORY_LABEL[prefix] ?? capitalise(prefix)
		const list = byLabel.get(label) ?? []
		list.push(cap)
		byLabel.set(label, list)
	}
	const known = CATEGORY_ORDER.filter((l) => byLabel.has(l))
	const rest = [...byLabel.keys()].filter((l) => !CATEGORY_ORDER.includes(l))
	return [...known, ...rest].map((label) => ({
		label,
		caps: byLabel.get(label)!,
	}))
}

/** Backend capability descriptions end with a full stop; in the role builder
 *  and the capability panel they read as list items, so drop it for display. */
export function capabilityLabel(cap: CapabilityInfo): string {
	return cap.description.replace(/\.\s*$/, '')
}

// The area nouns for derived role descriptions, in reading order.
const CATEGORY_NOUN: Record<string, string> = {
	billing: 'billing',
	team: 'team',
	service: 'services',
	server: 'servers',
	cluster: 'servers',
}
const NOUN_ORDER = ['billing', 'team', 'services', 'servers']

function listOf(items: string[]): string {
	if (items.length <= 2) return items.join(' and ')
	return `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`
}

/** One sentence for a capability set — "Manage servers; view billing". An area
 *  with any act-on capability reads "manage", a view-only area reads "view". */
export function describeCapabilities(caps: string[]): string {
	const level = new Map<string, 'manage' | 'view'>()
	for (const cap of caps) {
		const [prefix, action] = cap.split(':')
		const noun = CATEGORY_NOUN[prefix] ?? prefix
		const manages = action !== 'view' || level.get(noun) === 'manage'
		level.set(noun, manages ? 'manage' : 'view')
	}
	const rank = (n: string) => {
		const i = NOUN_ORDER.indexOf(n)
		return i === -1 ? NOUN_ORDER.length : i
	}
	const nouns = [...level.keys()].sort((a, b) => rank(a) - rank(b))
	const managed = nouns.filter((n) => level.get(n) === 'manage')
	const viewed = nouns.filter((n) => level.get(n) === 'view')
	const parts: string[] = []
	if (managed.length) parts.push(`Manage ${listOf(managed)}`)
	if (viewed.length)
		parts.push(`${managed.length ? 'view' : 'View'} ${listOf(viewed)}`)
	return parts.join('; ') || 'No capabilities'
}
