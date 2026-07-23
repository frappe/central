<script setup lang="ts">
import { computed } from 'vue'
import { Dialog } from 'frappe-ui'
import type { AssetRow } from '@/composables/useServers'

const props = defineProps<{
	server: AssetRow | null
	loading?: boolean
}>()

const emit = defineEmits<{
	'update:server': [server: AssetRow | null]
	confirm: [server: AssetRow]
}>()

const open = computed({
	get: () => !!props.server,
	set: (v: boolean) => {
		if (!v) emit('update:server', null)
	},
})

const name = computed(() => props.server?.title || props.server?.resource_id || '')
const dialogOptions = computed(() => ({
	actions: [
		{
			label: 'Yes, terminate',
			variant: 'solid' as const,
			theme: 'red' as const,
			loading: props.loading,
			onClick: () => {
				if (props.server) emit('confirm', props.server)
			},
		},
	],
}))
</script>

<template>
	<Dialog v-model="open" title="Terminate server" size="sm" :actions="dialogOptions.actions">
		<p class="text-p-base text-ink-gray-7">
			Permanently destroy <span class="font-semibold text-ink-gray-9">{{ name }}</span>? This can't be undone.
		</p>
	</Dialog>
</template>
