<script setup lang="ts">
import { type ColorScheme, SettingsRow, useColorScheme } from 'frappe-ui'

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
	{ value: 'system', label: 'Automatic', panes: ['light', 'dark'] },
	{ value: 'light', label: 'Light', panes: ['light'] },
	{ value: 'dark', label: 'Dark', panes: ['dark'] },
]
</script>

<template>
	<SettingsRow title="Theme" description="Choose how the dashboard looks." />

	<div class="grid grid-cols-3 gap-3">
		<button
			v-for="option in options"
			:key="option.value"
			type="button"
			:aria-pressed="colorScheme === option.value"
			class="grid grid-cols-2 overflow-hidden rounded-4 border focus-visible:focus-ring"
			:class="
				colorScheme === option.value
					? 'border-outline-gray-6'
					: 'border-outline-gray-2 hover:border-outline-gray-4'
			"
			@click="setColorScheme(option.value)"
		>
			<span
				v-for="(pane, index) in option.panes"
				:key="pane"
				class="flex overflow-hidden pl-4 pt-3"
				:class="[
						index === 0
							? 'bg-surface-gray-1'
							: 'border-l border-outline-gray-2 bg-surface-gray-2',
						option.panes.length === 2
							? 'aspect-[8/7]'
							: 'col-span-2 aspect-[16/7]',
					]"
			>
				<span
					class="grid shrink-0 grid-cols-[28%_1fr] grid-rows-[auto_1fr] overflow-hidden rounded-tl-1 hadow-lg"
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

					<!-- sidebar -->
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

					<!-- main content -->
					<span class="grid content-start grid-cols-2 gap-1 p-1">
						<span
							v-for="card in 4"
							:key="card"
							class="h-4 rounded-1 border"
							:class="[tones[pane].card, tones[pane].border]"
						/>
					</span>
				</span>
			</span>

			<span
				class="col-span-full flex items-center justify-between border-t border-outline-gray-2 px-2 py-1.5"
			>
				<span class="text-p-sm text-ink-gray-7">{{ option.label }}</span>
				<span
					class="size-3 rounded-full "
					:class="
						colorScheme === option.value
							? 'border-4 border-outline-gray-7'
							: 'border border-outline-gray-3'
					"
				/>
			</span>
		</button>
	</div>
</template>
