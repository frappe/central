<script setup lang="ts">
// A centered card floating over the map — the load/error/empty states share one
// shell. Actions (Retry, New server) go in the #action slot.
defineProps<{
	icon: string
	iconClass?: string
	title: string
	description: string
}>()
</script>

<template>
	<div
		class="pointer-events-none absolute inset-x-0 top-1/2 flex -translate-y-1/2 justify-center px-4"
	>
		<div
			class="pointer-events-auto flex w-[26rem] max-w-full flex-col items-center gap-1 rounded-xl border border-outline-gray-1 bg-surface-elevation-1 p-6 text-center shadow-lg"
		>
			<span
				:class="[icon, iconClass || 'text-ink-gray-4']"
				class="mb-2 size-6"
			/>
			<p class="text-base font-medium text-ink-gray-8">{{ title }}</p>
			<p class="text-sm text-ink-gray-5">{{ description }}</p>
			<slot name="action" />
		</div>
	</div>
</template>
