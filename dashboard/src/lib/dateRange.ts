const MONTHS = [
	'jan',
	'feb',
	'mar',
	'apr',
	'may',
	'jun',
	'jul',
	'aug',
	'sep',
	'oct',
	'nov',
	'dec',
]

const SEPARATOR = /[-,–—]|(?<![a-z])to(?![a-z])/i

interface DateParts {
	day: number
	month: number | null
	year: number | null
}

function monthOf(word: string): number | null {
	const index = MONTHS.indexOf(word.slice(0, 3))
	return index === -1 ? null : index + 1
}

function parseSide(text: string): DateParts | null {
	const compact = text.toLowerCase().replace(/\s+/g, '')
	const match = /^(?:(\d{1,2})([a-z]*)|([a-z]+)(\d{1,2}))(\d{4})?$/.exec(
		compact,
	)
	if (!match) return null

	const word = match[2] ?? match[3] ?? ''
	const month = word === '' ? null : monthOf(word)
	if (word !== '' && month === null) return null

	return {
		day: Number(match[1] ?? match[4]),
		month,
		year: match[5] === undefined ? null : Number(match[5]),
	}
}

function toIsoDate(year: number, month: number, day: number): string | null {
	const date = new Date(year, month - 1, day)
	if (date.getFullYear() !== year) return null
	if (date.getMonth() !== month - 1) return null
	if (date.getDate() !== day) return null
	const paddedMonth = String(month).padStart(2, '0')
	const paddedDay = String(day).padStart(2, '0')
	return `${year}-${paddedMonth}-${paddedDay}`
}

function shiftDays(
	year: number,
	month: number,
	day: number,
	delta: number,
): string {
	const date = new Date(year, month - 1, day + delta)
	return toIsoDate(date.getFullYear(), date.getMonth() + 1, date.getDate())!
}

function shiftMonths(
	year: number,
	month: number,
	day: number,
	months: number,
): string {
	const lastDay = new Date(year, month - months, 0).getDate()
	const date = new Date(year, month - 1 - months, Math.min(day, lastDay))
	return toIsoDate(date.getFullYear(), date.getMonth() + 1, date.getDate())!
}

function rollingStart(
	year: number,
	month: number,
	day: number,
	count: number,
	unit: string,
): string {
	if (unit === 'd') return shiftDays(year, month, day, -(count - 1))
	if (unit === 'w') return shiftDays(year, month, day, -(7 * count - 1))
	const months = unit === 'y' ? count * 12 : count
	return shiftMonths(year, month, day, months)
}

function parseRolling(
	text: string,
	year: number,
	month: number,
	day: number,
): string | null {
	const single = /^last (week|month|year)$/.exec(text)
	if (single) return rollingStart(year, month, day, 1, single[1][0])

	const match =
		/^(?:last|past)?\s*(\d+)\s*(d|days?|w|weeks?|m|months?|y|years?)$/.exec(
			text,
		)
	const count = match ? Number(match[1]) : 0
	if (!match || count < 1) return null
	return rollingStart(year, month, day, count, match[2][0])
}

function periodStart(
	text: string,
	year: number,
	month: number,
	day: number,
): string | null {
	if (text === 'this week') {
		const weekday = new Date(year, month - 1, day).getDay()
		return shiftDays(year, month, day, -((weekday + 6) % 7))
	}
	if (text === 'this month' || text === 'mtd') return toIsoDate(year, month, 1)
	if (text === 'this year' || text === 'ytd') return toIsoDate(year, 1, 1)
	return null
}

function parseRelative(text: string, today: string): [string, string] | null {
	const normalized = text.trim().toLowerCase().replace(/\s+/g, ' ')
	if (normalized === 'today') return [today, today]

	const [year, month, day] = today.split('-').map(Number)
	if (normalized === 'yesterday') {
		const previous = shiftDays(year, month, day, -1)
		return [previous, previous]
	}

	const start =
		periodStart(normalized, year, month, day) ??
		parseRolling(normalized, year, month, day)
	return start === null ? null : [start, today]
}

function explicitYears(
	first: DateParts,
	second: DateParts,
	startMonth: number,
	endMonth: number,
): [string, string] | null {
	const startYear = first.year ?? second.year
	const endYear = second.year ?? first.year
	if (startYear === null || endYear === null) return null

	const start = toIsoDate(startYear, startMonth, first.day)
	const end = toIsoDate(endYear, endMonth, second.day)
	if (start === null || end === null) return null
	return start <= end ? [start, end] : [end, start]
}

function latestEnd(month: number, day: number, today: string): string | null {
	const year = Number(today.slice(0, 4))
	const end = toIsoDate(year, month, day)
	if (end === null) return null
	if (end <= today) return end
	return toIsoDate(year - 1, month, day)
}

function startBefore(
	month: number,
	day: number,
	endMonth: number,
	end: string,
): [string, string] | null {
	const year = Number(end.slice(0, 4))
	const start = toIsoDate(year, month, day)
	if (start === null) return null
	if (start <= end) return [start, end]
	if (month <= endMonth) return [end, start]

	const wrapped = toIsoDate(year - 1, month, day)
	return wrapped === null ? null : [wrapped, end]
}

function latestRange(
	first: DateParts,
	second: DateParts,
	startMonth: number,
	endMonth: number,
	today: string,
): [string, string] | null {
	const end = latestEnd(endMonth, second.day, today)
	if (end === null) return null
	return startBefore(startMonth, first.day, endMonth, end)
}

export function parseDateRange(
	text: string,
	today: string,
): [string, string] | null {
	const relative = parseRelative(text, today)
	if (relative) return relative

	const sides = text
		.split(SEPARATOR)
		.map((side) => side.trim())
		.filter(Boolean)
	if (sides.length === 0 || sides.length > 2) return null

	const first = parseSide(sides[0])
	const second = sides.length === 2 ? parseSide(sides[1]) : first
	if (!first || !second) return null

	const startMonth = first.month ?? second.month
	const endMonth = second.month ?? first.month
	if (startMonth === null || endMonth === null) return null

	if (first.year !== null || second.year !== null)
		return explicitYears(first, second, startMonth, endMonth)
	return latestRange(first, second, startMonth, endMonth, today)
}
