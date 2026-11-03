/** One normalized event from `central.api.activity`. */

export type ActivityCategory =
	| 'action'
	| 'configuration'
	| 'snapshot'
	| 'site'
	| 'team'
	| 'member'
	| 'access'

export interface ActivityActor {
	label: string
	kind: 'user' | 'system'
	image?: string | null
}

export interface ActivityDetail {
	label: string
	/** Null when the value is new (created) or too large to diff. */
	from: string | null
	/** Null when the value was cleared or the change is summarized. */
	to: string | null
}

export interface ActivityResource {
	type: string
	name: string
	label: string
}

export interface ActivityEvent {
	id: string
	event: string
	category: ActivityCategory
	occurred_at: string
	actor: ActivityActor
	/** Translated; `{actor}` and `{resource}` mark the names to emphasise. */
	sentence: string
	resource: ActivityResource
	status: string | null
	details: ActivityDetail[]
	error: string | null
}

export interface ActivityPage {
	events: ActivityEvent[]
	next_cursor: string | null
}
