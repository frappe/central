import { dayjsLocal } from 'frappe-ui'
import { formatMemory } from '@/lib/units'
import type {
	ActivityCategory,
	ActivityDetail,
	ActivityEvent,
} from '@/types/activity'

export type StatusTheme = 'green' | 'amber' | 'red' | 'gray'

const EVENT_ICONS: Record<string, string> = {
	'server.created': 'lucide-server',
	'server.started': 'lucide-play',
	'server.stopped': 'lucide-square',
	'server.restarted': 'lucide-rotate-cw',
	'server.resized': 'lucide-maximize-2',
	'server.terminated': 'lucide-trash-2',
	'server.updated': 'lucide-sliders-horizontal',
	'server.ssh_keys_changed': 'lucide-key-round',
	'snapshot.created': 'lucide-camera',
	'snapshot.available': 'lucide-camera',
	'snapshot.failed': 'lucide-camera',
	'snapshot.deleted': 'lucide-trash-2',
	'site.created': 'lucide-globe',
	'site.claimed': 'lucide-globe',
	'site.deleted': 'lucide-trash-2',
	'domain.created': 'lucide-link',
	'domain.deleted': 'lucide-link-2-off',
	'team.impersonated': 'lucide-shield-check',
	'invitation.created': 'lucide-mail',
	'invitation.resent': 'lucide-mail',
	'invitation.accepted': 'lucide-mail-check',
	'invitation.declined': 'lucide-mail-x',
	'role.created': 'lucide-shield-plus',
	'role.updated': 'lucide-shield',
	'role.deleted': 'lucide-shield-minus',
	'ssh_key.created': 'lucide-key-round',
	'ssh_key.rotated': 'lucide-key-round',
	'ssh_key.deleted': 'lucide-trash-2',
}

const CATEGORY_ICONS: Record<ActivityCategory, string> = {
	action: 'lucide-zap',
	configuration: 'lucide-sliders-horizontal',
	snapshot: 'lucide-camera',
	site: 'lucide-globe',
	team: 'lucide-users',
	member: 'lucide-user-round',
	access: 'lucide-key-round',
}

/** Specific icon for each event, falling back to its category. */
export function getEventIcon(event: ActivityEvent): string {
	return (
		EVENT_ICONS[event.event] ?? CATEGORY_ICONS[event.category] ?? 'lucide-cpu'
	)
}

const STATUS_THEMES: Record<string, StatusTheme> = {
	Accepted: 'green',
	Available: 'green',
	Succeeded: 'green',
	Declined: 'red',
	Expired: 'red',
	Failed: 'red',
	'Timed Out': 'red',
	Pending: 'amber',
	Deleted: 'gray',
	Revoked: 'gray',
}

const DETAIL_UNITS: Record<string, (value: string) => string> = {
	Memory: (value) => formatMemory(Number(value)),
	Size: (value) => formatMemory(Number.parseFloat(value)),
	Disk: (value) => `${Number(value)} GB`,
}

// the row title already names these, so the summary carries the value alone
const VALUE_ONLY_LABELS = new Set(['Snapshot', 'Size'])

export function getStatusTheme(status: string): StatusTheme {
	return STATUS_THEMES[status] ?? 'gray'
}

export function formatDetailValue(label: string, value: string): string {
	return (DETAIL_UNITS[label] ?? String)(value)
}

/** One change as a quiet label and the value people scan for. */
export interface SummaryPart {
	label: string
	value: string
}

function getDetailSummary(detail: ActivityDetail): SummaryPart {
	const from = detail.from && formatDetailValue(detail.label, detail.from)
	const to = detail.to && formatDetailValue(detail.label, detail.to)
	if (from && to) return { label: detail.label, value: `${from} → ${to}` }
	if (from) return { label: detail.label, value: from }
	if (to)
		return VALUE_ONLY_LABELS.has(detail.label)
			? { label: '', value: to }
			: { label: detail.label, value: to }
	return { label: `${detail.label} changed`, value: '' }
}

// The sentence already names the resource, so a detail that only repeats it adds nothing.
export function getSummaryDetails(event: ActivityEvent): ActivityDetail[] {
	return event.details.filter(
		(detail) => detail.from || detail.to !== event.resource.label,
	)
}

/** Every item an event records, in order. */
export function getEventItems(event: ActivityEvent): SummaryPart[] {
	return getSummaryDetails(event).map(getDetailSummary)
}

/** The change inline when only one exists; multiple changes show their count instead. */
export function getEventSummary(event: ActivityEvent): SummaryPart[] {
	const items = getEventItems(event)
	return items.length === 1 ? items : []
}

export interface SentencePart {
	text: string
	role: 'actor' | 'resource' | null
}

/** Splits a sentence such as "{actor} restarted {resource}" into plain and named parts. */
export function getSentenceParts(event: ActivityEvent): SentencePart[] {
	return event.sentence
		.split(/(\{actor\}|\{resource\})/)
		.filter(Boolean)
		.map((part) => {
			if (part === '{actor}') return { text: event.actor.label, role: 'actor' }
			if (part === '{resource}')
				return { text: event.resource.label, role: 'resource' }
			return { text: part, role: null }
		})
}

/** Back-to-back repeats of one event by one actor on one resource, newest first. */
export interface ActivityCluster {
	key: string
	events: ActivityEvent[]
}

export interface ActivityMonth {
	label: string
	clusters: ActivityCluster[]
}

function clusterKey(event: ActivityEvent): string {
	// the label splits member events, which all sit on the team resource
	return [
		event.event,
		event.actor.label,
		event.resource.type,
		event.resource.name,
		event.resource.label,
	].join('|')
}

/** Groups a newest-first feed by month, then into runs of the same event. */
export function groupActivity(events: ActivityEvent[]): ActivityMonth[] {
	const months: ActivityMonth[] = []
	for (const event of events) {
		const label = dayjsLocal(event.occurred_at).format('MMMM YYYY')
		let month = months[months.length - 1]
		if (month?.label !== label) {
			month = { label, clusters: [] }
			months.push(month)
		}

		const key = clusterKey(event)
		const cluster = month.clusters[month.clusters.length - 1]
		if (cluster?.key === key) cluster.events.push(event)
		else month.clusters.push({ key, events: [event] })
	}
	return months
}
