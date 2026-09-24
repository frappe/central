<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { onErrorCaptured, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

// App-wide safety net: catches an unexpected render/lifecycle error anywhere
// below it and shows a recoverable fallback instead of a white screen. Routine
// API failures are handled upstream with inline or persistent alerts. This is for the
// unexpected. Navigating away clears it, so the rest of the app stays usable.
const failed = ref(false)
const route = useRoute()

onErrorCaptured((error) => {
	failed.value = true
	console.error('[central] unhandled UI error:', error)
	return false
})

watch(
	() => route.fullPath,
	() => {
		failed.value = false
	},
)

function reload(): void {
	window.location.reload()
}
</script>

<template>
	<div
		v-if="failed"
		class="flex min-h-screen flex-col items-center justify-center px-6 py-12 text-center"
	>
		<Alert
			class="w-full max-w-xl text-left"
			theme="red"
			title="This page ran into a problem"
			description="Reloading usually fixes it. If it keeps happening, check back in a few minutes."
			:primary-action="{ label: 'Reload page', onClick: reload }"
		/>
	</div>
	<slot v-else />
</template>
