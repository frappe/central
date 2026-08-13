<script setup lang="ts">
import { Button } from 'frappe-ui'
import { onErrorCaptured, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

// App-wide safety net: catches an unexpected render/lifecycle error anywhere
// below it and shows a recoverable fallback instead of a white screen. Routine
// API failures are handled upstream (inline states + toasts) — this is for the
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
		<div
			class="flex size-10 items-center justify-center rounded-6 bg-surface-red-1 text-ink-red-6"
		>
			<span class="lucide-triangle-alert size-5" aria-hidden="true" />
		</div>
		<p class="mt-4 text-base font-medium text-ink-gray-8">
			This page ran into a problem
		</p>
		<p class="mt-1 max-w-sm text-p-sm text-ink-gray-5">
			Reloading usually fixes it. If it keeps happening, check back in a few
			minutes.
		</p>
		<Button
			class="mt-5"
			variant="solid"
			label="Reload page"
			icon-left="lucide-refresh-cw"
			@click="reload"
		/>
	</div>
	<slot v-else />
</template>
