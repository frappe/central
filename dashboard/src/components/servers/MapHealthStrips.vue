<script setup lang="ts">
// Top-center strips over the map: stale-mirror warning first, then a load error
// with retry. Presentational — the page owns the data and the retry action.
defineProps<{ stale: string[]; error: string | null; hasRows: boolean }>()
defineEmits<{ retry: [] }>()
</script>

<template>
	<div
		class="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4"
	>
		<p
			v-if="stale.length"
			class="pointer-events-auto rounded-5 bg-surface-amber-1 px-3 py-2 text-p-sm text-ink-amber-6 shadow-sm"
		>
			Showing last-known data. Couldn't reach: {{ stale.join(', ') }}
		</p>
		<p
			v-else-if="error && hasRows"
			class="pointer-events-auto rounded-5 bg-surface-red-1 px-3 py-2 text-p-sm text-ink-red-6 shadow-sm"
		>
			{{ error }}
			<button class="ml-1 font-medium underline" @click="$emit('retry')">
				Retry
			</button>
		</p>
	</div>
</template>
