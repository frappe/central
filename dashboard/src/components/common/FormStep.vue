<script setup lang="ts">
// One rung of the creation form's timeline: the dot, the rail down to the next step,
// and the step's own heading. Every step on a page uses this so the rail stays one line.
defineProps<{ title?: string; last?: boolean }>()
</script>

<template>
	<div class="flex gap-4">
		<div class="flex flex-col items-center pt-1">
			<span class="size-2.5 shrink-0 rounded-full bg-[var(--ink-gray-9)]" />
			<span v-if="!last" class="mt-1.5 w-px grow bg-[var(--outline-gray-2)]" />
		</div>
		<div class="min-w-0 flex-1" :class="last ? 'pb-1' : 'pb-6'">
			<h2 v-if="title" class="text-sm font-medium text-ink-gray-7">
				{{ title }}
			</h2>
			<div :class="title ? 'mt-2' : ''">
				<slot />
			</div>
		</div>
	</div>
</template>
