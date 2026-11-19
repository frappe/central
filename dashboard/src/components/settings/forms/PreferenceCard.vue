<script setup lang="ts" generic="TPane extends string">
interface PreferenceCardProps {
	label: string
	panes: TPane[]
	isSelected: boolean
}

defineProps<PreferenceCardProps>()
</script>

<template>
	<button
		type="button"
		:aria-pressed="isSelected"
		class="grid grid-cols-2 overflow-hidden rounded-4 border transition-colors focus-visible:focus-ring"
		:class="
			isSelected
				? 'border-outline-gray-6'
				: 'border-outline-gray-2 hover:border-outline-gray-4'
		"
	>
		<span
			v-for="(pane, index) in panes"
			:key="pane"
			class="flex overflow-hidden bg-surface-gray-1 pl-2 pt-2 sm:pl-4 sm:pt-3"
			:class="[
				index > 0 && 'border-l border-outline-gray-2',
				panes.length === 2 ? 'aspect-[8/7]' : 'col-span-2 aspect-[16/7]',
			]"
		>
			<slot name="pane" :pane="pane" />
		</span>

		<span
			class="col-span-full flex items-center justify-between border-t border-outline-gray-2 px-1.5 py-1 sm:px-2 sm:py-1.5"
		>
			<span class="text-p-xs sm:text-p-sm text-ink-gray-7">
				{{ label }}
			</span>
			<span
				class="size-3 rounded-full"
				:class="
					isSelected
						? 'border-4 border-outline-gray-7'
						: 'border border-outline-gray-3'
				"
			/>
		</span>
	</button>
</template>
