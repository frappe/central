<script setup lang="ts">
import { Alert } from 'frappe-ui'

// Top-center strips over the map: stale-mirror warning first, then a load error
// with retry. Presentational — the page owns the data and the retry action.
defineProps<{ stale: string[]; error: string | null; hasRows: boolean }>()
defineEmits<{ retry: [] }>()
</script>

<template>
	<div
		class="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4"
	>
		<Alert
			v-if="stale.length"
			class="pointer-events-auto w-full max-w-xl shadow-sm"
			theme="amber"
			:title="`Showing last-known data. Couldn't reach: ${stale.join(', ')}`"
		/>
		<Alert
			v-else-if="error && hasRows"
			class="pointer-events-auto w-full max-w-xl shadow-sm"
			theme="red"
			:title="error"
			:primary-action="{ label: 'Retry', onClick: () => $emit('retry') }"
		/>
	</div>
</template>
