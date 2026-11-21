<script setup lang="ts">
import { type ColorScheme, SettingsRow, useColorScheme } from 'frappe-ui'
import FleetViewPreference from './FleetViewPreference.vue'
import PreferenceCard from './PreferenceCard.vue'

const { colorScheme, setColorScheme } = useColorScheme()

const tones = {
	light: {
		page: 'bg-white',
		sidebar: 'bg-gray-50',
		bar: 'bg-gray-300',
		card: 'bg-gray-100',
		border: 'border-gray-200',
	},
	dark: {
		page: 'bg-dark-gray-950',
		sidebar: 'bg-transparent',
		bar: 'bg-dark-gray-500',
		card: 'bg-dark-gray-800',
		border: 'border-dark-gray-800',
	},
}

type Tone = keyof typeof tones

interface ThemeOption {
	value: ColorScheme
	label: string
	panes: Tone[]
}

const options: ThemeOption[] = [
	{ value: 'system', label: 'System', panes: ['light', 'dark'] },
	{ value: 'light', label: 'Light', panes: ['light'] },
	{ value: 'dark', label: 'Dark', panes: ['dark'] },
]
</script>

<template>
	<div class="mt-6">
		<SettingsRow
			class="!py-0"
			title="Theme"
			description="Switch between light, dark, or system theme."
		/>

		<div class="mt-4 grid grid-cols-3 gap-3">
			<PreferenceCard
				v-for="option in options"
				:key="option.value"
				:label="option.label"
				:panes="option.panes"
				:is-selected="colorScheme === option.value"
				@click="setColorScheme(option.value)"
			>
				<template #pane="{ pane }">
					<span
						class="grid shrink-0 grid-cols-[28%_1fr] grid-rows-[auto_1fr] overflow-hidden rounded-tl-1 shadow-lg"
						:class="[tones[pane].page, tones[pane].border]"
						:style="{ width: `${option.panes.length * 100}%` }"
					>
						<span
							class="col-span-2 flex border-b p-1"
							:class="tones[pane].border"
						>
							<svg class="h-1">
								<circle cx="2" cy="2" r="2" class="fill-red-500" />
								<circle cx="8" cy="2" r="2" class="fill-amber-500" />
								<circle cx="14" cy="2" r="2" class="fill-green-500" />
							</svg>
						</span>

						<span
							class="flex flex-col gap-1 border-r p-1"
							:class="[tones[pane].sidebar, tones[pane].border]"
						>
							<span
								v-for="bar in 3"
								:key="bar"
								class="h-[3px] rounded-1"
								:class="tones[pane].bar"
							/>
						</span>

						<span class="grid content-start grid-cols-2 gap-1 p-1">
							<span
								v-for="card in 4"
								:key="card"
								class="h-3 rounded-1 border sm:h-4"
								:class="[tones[pane].card, tones[pane].border]"
							/>
						</span>
					</span>
				</template>
			</PreferenceCard>
		</div>

		<FleetViewPreference />
	</div>
</template>
