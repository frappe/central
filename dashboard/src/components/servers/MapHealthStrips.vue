<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { __ } from '@/lib/translate'

// Top-center strips over the map: stale-mirror warning first, then a load error
// with retry. Presentational — the page owns the data and the retry action.
defineProps<{ stale: string[]; error: string | null; hasRows: boolean }>()
defineEmits<{ retry: [] }>()

const refreshMapErrorTitle = __("Couldn't refresh the map")

function getUnreachableDescription(regions: string[]): string {
	return __("Couldn't reach: {0}", [regions.join(', ')])
}
</script>

<template>
	<div
		class="pointer-events-none absolute inset-x-0 top-2 flex justify-center px-2"
	>
		<Alert
			v-if="stale.length"
			class="pointer-events-auto w-full max-w-xl shadow-sm"
			theme="amber"
			:title="__('Showing last-known data')"
			:description="getUnreachableDescription(stale)"
		/>
		<Alert
			v-else-if="error && hasRows"
			class="pointer-events-auto w-full max-w-xl shadow-sm"
			theme="red"
			:title="refreshMapErrorTitle"
			:description="error"
			:primary-action="{ label: __('Retry'), onClick: () => $emit('retry') }"
		/>
	</div>
</template>
