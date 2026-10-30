/** One normalized event from `central.api.activity.server_activity`. */

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

export interface ActivityEvent {
	id: string
	event: string
	category: ActivityCategory
	occurred_at: string
	actor: ActivityActor
	title: string
	status: string | null
	details: ActivityDetail[]
	error: string | null
	/** Present only for a team admin. */
	ip_address?: string
}

export interface ServerActivity {
	events: ActivityEvent[]
	next_cursor: string | null
}
