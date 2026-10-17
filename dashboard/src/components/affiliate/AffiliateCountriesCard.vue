<script setup lang="ts">
import { Button, Select } from 'frappe-ui'
import { computed, ref } from 'vue'
import AffiliateCountriesDialog from '@/components/affiliate/AffiliateCountriesDialog.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import { countryPlace } from '@/lib/countries'
import { COUNTRY_DOTS } from '@/lib/countryDots'
import {
	flagEmoji,
	MAP_HEIGHT,
	MAP_WIDTH,
	type MapHighlight,
} from '@/lib/serverMap'
import type { FunnelRow } from '@/types/affiliates'

interface AffiliateCountriesCardProps {
	rows: FunnelRow[]
}

const props = defineProps<AffiliateCountriesCardProps>()

const TOP = 10
// Lightest to darkest, so a stronger country reads darker.
const SHADES = [
	'var(--surface-blue-3)',
	'var(--surface-blue-5)',
	'var(--surface-blue-7)',
	'var(--surface-blue-9)',
]

const chosen = ref('')
const dialogOpen = ref(false)

// Countries with the most signups first; clicks break a tie.
const ranked = computed(() =>
	[...props.rows].sort(
		(a, b) => b.signed_up - a.signed_up || b.visited - a.visited,
	),
)
const top = computed(() =>
	ranked.value.slice(0, TOP).map((row, index) => ({ ...row, rank: index + 1 })),
)
const options = computed(() => [
	{ label: 'All countries', value: '' },
	...ranked.value.map(({ label }) => ({ label, value: label })),
])
const rate = (row: FunnelRow): string =>
	row.signed_up ? `${Math.round((row.converted / row.signed_up) * 100)}%` : '–'

const conversion = (row: FunnelRow): number =>
	row.signed_up ? row.converted / row.signed_up : 0

// Each known country's dots, shaded by its signups and conversion together.
const highlights = computed<MapHighlight[]>(() => {
	const rows = chosen.value
		? props.rows.filter((row) => row.label === chosen.value)
		: props.rows
	const mostSignups = Math.max(...rows.map((row) => row.signed_up), 1)
	const bestConversion = Math.max(...rows.map(conversion), Number.EPSILON)

	return rows.flatMap((row) => {
		const place = countryPlace(row.label)
		const path = place && COUNTRY_DOTS[place.code]
		if (!place || !path) return []

		const score =
			(row.signed_up / mostSignups + conversion(row) / bestConversion) / 2
		const shade = Math.min(SHADES.length - 1, Math.floor(score * SHADES.length))
		return [
			{
				id: row.label,
				path,
				color: SHADES[shade],
				lat: place.lat,
				lng: place.lng,
				label: `${flagEmoji(place.code)} ${row.label}`,
				detail: `${row.visited} clicks · ${row.signed_up} signups · ${rate(row)} conversion`,
			},
		]
	})
})
</script>

<template>
	<section
		class="grid overflow-hidden rounded-6 border border-outline-gray-1 bg-surface-base lg:grid-cols-[minmax(0,1fr)_24rem]"
	>
		<div class="flex min-w-0 flex-col gap-4 p-5">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<h2 class="text-base-semibold text-ink-gray-8">
					Where your customers come from
				</h2>
				<Select
					v-model="chosen"
					:options="options"
					aria-label="Country"
					class="w-44"
				/>
			</div>
			<p v-if="!rows.length" class="text-p-sm text-ink-gray-5">
				No visits in this period.
			</p>
			<template v-else>
				<div
					class="w-full"
					:style="{ aspectRatio: `${MAP_WIDTH} / ${MAP_HEIGHT}` }"
				>
					<ServerMap :interactive="false" :highlights="highlights" />
				</div>
				<div class="flex items-center gap-5 text-sm text-ink-gray-6">
					<span class="flex items-center gap-2">
						<span class="size-3 rounded-full bg-surface-blue-9" />
						More signups and conversion
					</span>
					<span class="flex items-center gap-2">
						<span class="size-3 rounded-full bg-surface-blue-3" />
						Fewer
					</span>
				</div>
			</template>
		</div>

		<div
			class="flex min-w-0 flex-col gap-3 border-t border-outline-gray-1 p-5 lg:border-l lg:border-t-0"
		>
			<h2 class="text-base-semibold text-ink-gray-8">
				Top countries by signups
			</h2>
			<p v-if="!rows.length" class="text-p-sm text-ink-gray-5">
				No signups in this period.
			</p>
			<template v-else>
				<div
					class="flex flex-col text-sm"
					role="table"
					aria-label="Top countries by signups"
				>
					<div
						class="grid grid-cols-[1.5rem_minmax(0,1fr)_3.5rem_4.5rem] gap-2 rounded-6 bg-surface-gray-2 px-3 py-2 text-ink-gray-5"
						role="row"
					>
						<span role="columnheader">#</span>
						<span role="columnheader">Country</span>
						<span class="text-right" role="columnheader">Signups</span>
						<span class="text-right" role="columnheader">Conversion</span>
					</div>
					<div
						v-for="row in top"
						:key="row.label"
						class="grid grid-cols-[1.5rem_minmax(0,1fr)_3.5rem_4.5rem] items-center gap-2 border-b border-outline-gray-1 px-3 py-2.5 last:border-b-0"
						role="row"
					>
						<span class="text-ink-gray-5" role="cell">{{ row.rank }}</span>
						<span
							class="flex min-w-0 items-center gap-2 text-ink-gray-9"
							role="cell"
						>
							<span aria-hidden="true">
								{{ flagEmoji(countryPlace(row.label)?.code) }}
							</span>
							<span class="truncate">{{ row.label }}</span>
						</span>
						<span class="text-right tabular-nums text-ink-gray-9" role="cell">
							{{ row.signed_up }}
						</span>
						<span class="text-right tabular-nums text-ink-gray-9" role="cell">
							{{ rate(row) }}
						</span>
					</div>
				</div>
				<Button
					variant="ghost"
					class="w-fit"
					icon-right="lucide-arrow-right"
					label="View all countries"
					@click="dialogOpen = true"
				/>
			</template>
		</div>
		<AffiliateCountriesDialog v-model="dialogOpen" :rows="ranked" />
	</section>
</template>
