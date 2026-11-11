<script setup lang="ts">
import { SettingsRow } from 'frappe-ui'
import {
	type FleetView,
	type FleetViewChoice,
	fleetViewChoice,
} from '@/composables/useFleetViewChoice'
import PreferenceCard from './PreferenceCard.vue'

interface FleetViewOption {
	value: FleetViewChoice
	label: string
	panes: FleetView[]
}

const OPTIONS: FleetViewOption[] = [
	{ value: 'auto', label: 'Automatic', panes: ['map', 'list'] },
	{ value: 'map', label: 'Map', panes: ['map'] },
	{ value: 'list', label: 'List', panes: ['list'] },
]

const LAND = [
	'..####....#####.',
	'.#####..########',
	'..###...#######.',
	'...##...####.##.',
	'...###...##...#.',
	'....#.........##',
]

const DOT_GAP = 6

const landDots = LAND.flatMap((row, rowIndex) =>
	[...row].flatMap((cell, cellIndex) =>
		cell === '#'
			? [{ x: cellIndex * DOT_GAP + 3, y: rowIndex * DOT_GAP + 3 }]
			: [],
	),
)

const PINS = [
	{ x: 15, y: 15, color: 'var(--ink-green-6)' },
	{ x: 63, y: 9, color: 'var(--ink-green-6)' },
	{ x: 75, y: 21, color: 'var(--ink-amber-6)' },
]
</script>

<template>
	<div class="mt-8">
		<SettingsRow
			class="!py-0"
			title="Servers view"
			description="Automatic uses List when a region has more than 10 servers."
		/>

		<div class="mt-4 grid grid-cols-3 gap-3">
			<PreferenceCard
				v-for="option in OPTIONS"
				:key="option.value"
				:label="option.label"
				:panes="option.panes"
				:is-selected="fleetViewChoice === option.value"
				@click="fleetViewChoice = option.value"
			>
				<template #pane="{ pane }">
					<span
						class="flex w-full overflow-hidden rounded-tl-1 bg-surface-base shadow-sm"
					>
						<template v-if="pane === 'map'">
							<svg
								class="min-w-0 flex-1 self-center p-1"
								:viewBox="option.panes.length === 1 ? '0 0 96 36' : '24 0 72 36'"
								aria-hidden="true"
							>
								<circle
									v-for="dot in landDots"
									:key="`${dot.x}-${dot.y}`"
									:cx="dot.x"
									:cy="dot.y"
									r="1"
									style="fill: var(--ink-gray-3)"
								/>
								<circle
									v-for="pin in PINS"
									:key="`${pin.x}-${pin.y}`"
									:cx="pin.x"
									:cy="pin.y"
									r="2.5"
									:style="{ fill: pin.color }"
								/>
							</svg>

							<span
								v-if="option.panes.length === 1"
								class="flex w-1/4 shrink-0 flex-col gap-1 border-l border-outline-gray-2 p-1"
							>
								<span
									v-for="bar in 4"
									:key="bar"
									class="h-1 rounded-1 bg-surface-gray-5"
								/>
							</span>
						</template>

						<span v-else class="flex w-full flex-col">
							<span
								v-for="row in 4"
								:key="row"
								class="flex items-center gap-1 border-b border-outline-gray-2 p-1"
							>
								<span class="size-1.5 shrink-0 rounded-1 bg-surface-gray-4" />
								<span class="h-1 w-1/3 rounded-1 bg-surface-gray-5" />
								<span class="h-1 w-1/6 rounded-1 bg-surface-gray-4" />
								<span class="h-1 w-1/6 rounded-1 bg-surface-gray-4" />
							</span>
						</span>
					</span>
				</template>
			</PreferenceCard>
		</div>
	</div>
</template>
