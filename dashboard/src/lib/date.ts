// Human-readable billing dates. The backend serialises ISO date strings
// ("2026-01-31"); raw "2026-01-01 → 2026-01-31" reads like a database row, not a
// billing period. These collapse it to how a person says it.
// Ported from the legacy dashboard's utils/date.js.

const FULL = [
	'January',
	'February',
	'March',
	'April',
	'May',
	'June',
	'July',
	'August',
	'September',
	'October',
	'November',
	'December',
]
const ABBR = [
	'Jan',
	'Feb',
	'Mar',
	'Apr',
	'May',
	'Jun',
	'Jul',
	'Aug',
	'Sep',
	'Oct',
	'Nov',
	'Dec',
]

interface DateParts {
	y: number
	m: number
	day: number
}

function parts(d: string | null | undefined): DateParts | null {
	if (!d) return null
	const [y, m, day] = String(d).split(/[-T ]/).map(Number)
	if (!y || !m || !day) return null
	return { y, m, day }
}

function lastDay(y: number, m: number): number {
	return new Date(y, m, 0).getDate() // m is 1-based → day 0 of next month
}

/** "1 Jan 2026" */
export function shortDate(d: string | null | undefined): string {
	const p = parts(d)
	if (!p) return d || ''
	return `${p.day} ${ABBR[p.m - 1]} ${p.y}`
}

// Collapse a [start, end] span to the shortest unambiguous phrasing:
//   whole calendar month   → "January 2026"
//   range within one month → "1–15 Jan 2026"
//   spanning months/years  → "28 Jan – 4 Feb 2026"
export function billingPeriod(
	start: string | null | undefined,
	end: string | null | undefined,
): string {
	const s = parts(start)
	const e = parts(end)
	if (!s || !e) return [start, end].filter(Boolean).join(' → ')

	if (
		s.day === 1 &&
		s.y === e.y &&
		s.m === e.m &&
		e.day === lastDay(e.y, e.m)
	) {
		return `${FULL[s.m - 1]} ${s.y}`
	}
	if (s.y === e.y && s.m === e.m) {
		return `${s.day}–${e.day} ${ABBR[s.m - 1]} ${s.y}`
	}
	const startYear = s.y === e.y ? '' : ` ${s.y}`
	return `${s.day} ${ABBR[s.m - 1]}${startYear} – ${e.day} ${ABBR[e.m - 1]} ${e.y}`
}
