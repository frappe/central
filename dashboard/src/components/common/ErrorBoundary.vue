<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, onErrorCaptured, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useSupport } from '@/composables/useSupport'

// App-wide safety net: catches an unexpected render/lifecycle error anywhere
// below it and shows a recoverable fallback instead of a white screen. Routine
// API failures are handled upstream with inline or persistent alerts. This is for the
// unexpected. Navigating away clears it, so the rest of the app stays usable.
const failed = ref(false)
const route = useRoute()
const { getContactSupportOption } = useSupport()

// The ticket names the page by its route pattern, such as /join/:token. The real path
// can hold an invitation token, which must not reach a third-party URL.
const supportAction = computed(() => {
	const option = getContactSupportOption({
		Page:
			route.matched[route.matched.length - 1]?.path ?? String(route.name ?? ''),
	})
	return option
		? { label: 'Contact support', onClick: option.onClick }
		: undefined
})

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
			description="Reload the page to try again. If the problem continues, contact support and say what you were doing."
			:primary-action="{ label: 'Reload page', onClick: reload }"
			:secondary-action="supportAction"
		/>
	</div>
	<slot v-else />
</template>
