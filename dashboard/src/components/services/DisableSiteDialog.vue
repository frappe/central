<script setup lang="ts">
import { computed } from 'vue'
import { Dialog } from 'frappe-ui'

// Confirm before revoking a site's AI. It's reversible (re-enabling mints a fresh
// key), but it cuts off any app using the current key — so it warrants a pause.
const props = defineProps<{
	site: string | null
	loading?: boolean
}>()

const emit = defineEmits<{
	'update:site': [site: string | null]
	confirm: [site: string]
}>()

const open = computed({
	get: () => !!props.site,
	set: (v: boolean) => {
		if (!v) emit('update:site', null)
	},
})

const dialogOptions = computed(() => ({
	title: 'Disable AI for this site',
	message: `Revoke the key for ${props.site}? Anything using it — including your own apps — will stop working. You can re-enable later, which issues a new key.`,
	actions: [
		{
			label: 'Disable',
			variant: 'solid' as const,
			theme: 'red' as const,
			loading: props.loading,
			onClick: () => {
				if (props.site) emit('confirm', props.site)
			},
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:message="dialogOptions.message"
		:actions="dialogOptions.actions"
	/>
</template>
