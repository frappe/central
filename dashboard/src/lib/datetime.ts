import { dayjs, dayjsLocal } from 'frappe-ui'

// Raven reads its timestamps as UTC and then shows local time. Frappe does not
// store UTC: a datetime is a naive clock in the site timezone. dayjsLocal does
// that conversion once systemTimezone is set at startup. These helpers are the
// same shapes Raven's frontend uses, on that clock.

type When = string | number | null | undefined

function at(value: When) {
	if (value == null || value === '') return null
	const date =
		typeof value === 'number'
			? dayjs(value > 1e12 ? value : value * 1000)
			: dayjsLocal(value)
	return date.isValid() ? date : null
}

/** "Today", "Yesterday", "Sep 21st", or "Sep 21st, 2025". */
export function formatCalendarDate(value: When): string {
	const date = at(value)
	if (!date) return ''
	const today = dayjs()
	if (date.isSame(today, 'day')) return 'Today'
	if (date.isSame(today.subtract(1, 'day'), 'day')) return 'Yesterday'
	if (date.isSame(today, 'year')) return date.format('MMM Do')
	return date.format('MMM Do, YYYY')
}

/** "Sep 21, 10:23 AM". Empty when unset. */
export function formatDateTime(value: When): string {
	const date = at(value)
	if (!date) return ''
	return date.format('MMM D, h:mm A')
}

/** "2 hours ago". Empty when unset. */
export function timeAgo(value: When): string {
	const date = at(value)
	if (!date) return ''
	return date.fromNow()
}

export interface TimestampZone {
	zone: string
	date: string
	time: string
}

/** UTC and browser-local wall clocks for a timestamp popover. */
export function timestampZones(
	value: When,
): { utc: TimestampZone; local: TimestampZone } | null {
	const date = at(value)
	if (!date) return null
	const utc = date.utc()
	return {
		utc: {
			zone: 'UTC',
			date: utc.format('MMMM D, YYYY'),
			time: utc.format('hh:mm:ss A'),
		},
		local: {
			zone: gmtLabel(date.utcOffset()),
			date: date.format('MMMM D, YYYY'),
			time: date.format('hh:mm:ss A'),
		},
	}
}

function gmtLabel(offsetMinutes: number): string {
	const sign = offsetMinutes < 0 ? '-' : '+'
	const absolute = Math.abs(offsetMinutes)
	const hours = Math.floor(absolute / 60)
	const minutes = absolute % 60
	return `GMT${sign}${hours}${minutes ? `:${String(minutes).padStart(2, '0')}` : ''}`
}
