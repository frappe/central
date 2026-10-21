import { dayjs, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { submitOrThrow } from '@/lib/frappeCall'
import type {
	AffiliateLink,
	AffiliateRetention,
	AffiliateState,
	AffiliateSummary,
	FunnelCounts,
	FunnelRow,
	LinkProduct,
	NewAffiliateLink,
} from '@/types/affiliates'

const ISO_DATE = 'YYYY-MM-DD'

/** The quick ranges the date picker offers, as [from, to] with both dates included. */
export const AFFILIATE_DATE_PRESETS: {
	label: string
	range: () => string[]
}[] = [
	{ label: 'Last 7 days', range: () => lastDays(7) },
	{ label: 'Last 30 days', range: () => lastDays(30) },
	{ label: 'Last 90 days', range: () => lastDays(90) },
	{
		label: 'This year',
		range: () => [
			dayjs().startOf('year').format(ISO_DATE),
			dayjs().format(ISO_DATE),
		],
	},
]

function lastDays(days: number): string[] {
	return [
		dayjs()
			.subtract(days - 1, 'day')
			.format(ISO_DATE),
		dayjs().format(ISO_DATE),
	]
}

/** The sources a new link offers. They become `utm_source`. */
export const AFFILIATE_SOURCES = [
	{ label: 'YouTube', value: 'youtube' },
	{ label: 'Instagram', value: 'instagram' },
	{ label: 'LinkedIn', value: 'linkedin' },
	{ label: 'Other', value: 'other' },
]

/** The funnel counts a bar chart plots, in light tints of the performance chart's colors. */
export const FUNNEL_SERIES = {
	visited: { label: 'Clicks', color: 'var(--surface-blue-4)' },
	signed_up: { label: 'Signups', color: 'var(--surface-purple-4)' },
	converted: { label: 'Paying', color: 'var(--surface-green-4)' },
}

// Commission is not decided yet. This sample rate only draws the earnings card.
const SAMPLE_EARNING_PER_CUSTOMER = 50

/** Sample earnings from paying customers at the sample rate. */
export function sampleEarnings(converted: number): number {
	return converted * SAMPLE_EARNING_PER_CUSTOMER
}

/** Sample earnings for each click. */
export function sampleEarningsPerClick(totals: FunnelCounts): number {
	return totals.visited ? sampleEarnings(totals.converted) / totals.visited : 0
}

const NO_COUNTS: FunnelCounts = {
	visited: 0,
	signed_up: 0,
	created_site: 0,
	added_billing: 0,
	converted: 0,
}

export interface LinkRow extends FunnelCounts {
	slug: string
	isMain: boolean
	product: string | null
	utm_source: string | null
	utm_campaign: string | null
}

/** The address a slug is shared at. */
export function affiliateUrl(slug: string): string {
	return `${window.location.origin}/r/${slug}`
}

// The signed-in user's own affiliate account: its status, and once Active, its links,
// funnel and retention. Not team-scoped, so a team switch changes nothing.
export function useAffiliate() {
	const account = useCall<AffiliateState | null>({ url: method(API.affiliate) })
	const applyCall = useCall<AffiliateState, Record<string, never>>({
		url: method(API.applyAffiliate),
		method: 'POST',
		immediate: false,
	})

	// [from, to], both included. Clearing it falls back to the last 30 days.
	const dateRange = ref<string[]>(lastDays(30))
	const period = computed(() =>
		dateRange.value?.length === 2 ? dateRange.value : lastDays(30),
	)
	const summary = useCall<
		AffiliateSummary,
		{ from_date: string; to_date: string }
	>({
		url: method(API.affiliateSummary),
		params: () => ({
			from_date: period.value[0],
			to_date: period.value[1],
		}),
		immediate: false,
		refetch: true,
	})
	const links = useCall<AffiliateLink[]>({
		url: method(API.affiliateLinks),
		immediate: false,
	})
	const retention = useCall<AffiliateRetention>({
		url: method(API.affiliateRetention),
		immediate: false,
	})
	const products = useCall<LinkProduct[]>({
		url: method(API.affiliateLinkProducts),
		immediate: false,
	})
	const createCall = useCall<{ slug: string }, NewAffiliateLink>({
		url: method(API.createAffiliateLink),
		method: 'POST',
		immediate: false,
	})

	const isActive = computed(() => account.data?.status === 'Active')
	watch(
		isActive,
		(active) => {
			if (!active) return
			summary.reload()
			links.reload()
			retention.reload()
			products.reload()
		},
		{ immediate: true },
	)

	const applying = ref(false)
	const applyError = ref<unknown>(null)
	async function apply(): Promise<void> {
		applying.value = true
		applyError.value = null
		try {
			await submitOrThrow(applyCall, {})
			account.reload()
		} catch (error) {
			applyError.value = error
		} finally {
			applying.value = false
		}
	}

	/** Creates the link and reloads the list. Throws, so the dialog can show the reason. */
	async function createLink(link: NewAffiliateLink): Promise<string> {
		await submitOrThrow(createCall, link)
		links.reload()
		return createCall.data?.slug ?? link.slug
	}

	const totals = computed(() => summary.data?.totals ?? NO_COUNTS)
	const linkRows = computed<LinkRow[]>(() => {
		const counts = new Map(
			(summary.data?.by_link ?? []).map(({ link, ...row }) => [link, row]),
		)
		const code = account.data?.affiliate_code ?? ''
		const main: LinkRow = {
			slug: code,
			isMain: true,
			product: null,
			utm_source: null,
			utm_campaign: null,
			...(counts.get(null) ?? NO_COUNTS),
		}
		const named = (links.data ?? []).map((link) => ({
			...link,
			isMain: false,
			...(counts.get(link.slug) ?? NO_COUNTS),
		}))
		return [main, ...named]
	})

	return {
		account,
		summary,
		links,
		retention,
		dateRange,
		applying,
		applyError,
		apply,
		createLink,
		totals,
		linkRows,
		bySource: computed(() =>
			toRows(summary.data?.by_source ?? [], (row) => row.source ?? 'No source'),
		),
		byProduct: computed(() =>
			toRows(
				summary.data?.by_product ?? [],
				(row) => row.product ?? 'Frappe Cloud',
			),
		),
		byCountry: computed(() =>
			toRows(summary.data?.by_country ?? [], (row) => row.country ?? 'Unknown'),
		),
		products: computed<LinkProduct[]>(() => products.data ?? []),
	}
}

function toRows<Row extends FunnelCounts>(
	rows: Row[],
	label: (row: Row) => string,
): FunnelRow[] {
	return rows.map((row) => ({ ...row, label: label(row) }))
}
