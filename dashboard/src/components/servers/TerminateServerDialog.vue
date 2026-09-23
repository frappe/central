<script setup lang="ts">
import { Badge, Checkbox, LoadingIndicator } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { useServerHostnames } from '@/composables/useServerHostnames'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSnapshotPricing } from '@/composables/useSnapshots'
import { money } from '@/lib/format'

interface TerminateServerDialogProps {
	target: VirtualMachineRow | null
	loading?: boolean
	error?: string
	/** The viewer holds server:snapshot, so a final snapshot can be offered. */
	canSnapshot?: boolean
}

// Lists what stops working before the customer confirms. The list is advice: a failed
// read does not block the terminate, which removes every route either way.
const props = defineProps<TerminateServerDialogProps>()
const emit = defineEmits<{
	'update:target': [value: VirtualMachineRow | null]
	confirm: [value: VirtualMachineRow, takeSnapshot: boolean]
}>()

const target = computed({
	get: () => props.target,
	set: (value: VirtualMachineRow | null) => emit('update:target', value),
})
const {
	hostnames,
	loading: listing,
	error: listError,
} = useServerHostnames(computed(() => props.target))
const name = computed(() => props.target?.title || props.target?.resource_id)

const takeSnapshot = ref(false)
watch(
	() => props.target,
	() => {
		takeSnapshot.value = false
	},
)
const { rate, currency, freePerServer } = useSnapshotPricing(
	computed(() => props.target?.region ?? null),
)
const snapshotNote = computed(() => {
	if (rate.value == null)
		return 'Snapshot storage has no price in this region yet.'
	const perGb = money(rate.value, currency.value, { trimTrailingZeros: true })
	return `The server stops first. The snapshot is free while it is one of this server's ${freePerServer.value} newest snapshots. After that it costs ${perGb} per GB per month until you delete it.`
})
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		title="Terminate server"
		confirm-label="Yes, terminate"
		theme="red"
		size="md"
		:loading="loading"
		:error="error"
		@confirm="emit('confirm', $event, takeSnapshot)"
	>
		<div class="space-y-3">
			<p class="text-p-base text-ink-gray-7">
				Permanently destroy
				<span class="font-semibold text-ink-gray-9">{{ name }}</span>? This
				can't be undone.
			</p>

			<div
				v-if="listing"
				class="flex items-center gap-2 text-p-sm text-ink-gray-5"
			>
				<LoadingIndicator class="h-4 w-4" />
				Checking its sites and domains…
			</div>
			<p v-else-if="listError" class="text-p-sm text-ink-gray-5">
				We couldn't list its sites and domains. Terminating still removes them.
			</p>
			<p v-else-if="!hostnames.length" class="text-p-sm text-ink-gray-5">
				No sites or custom domains point to this server.
			</p>
			<div v-else class="space-y-1.5">
				<p class="text-p-sm text-ink-gray-7">
					These stop working, and their routes are removed:
				</p>
				<ul
					class="max-h-40 space-y-1 overflow-y-auto rounded-6 border border-outline-gray-2 px-3 py-2"
				>
					<li
						v-for="entry in hostnames"
						:key="entry.hostname"
						class="flex items-center justify-between gap-3 text-p-sm"
					>
						<span class="truncate text-ink-gray-9">{{ entry.hostname }}</span>
						<Badge :label="entry.kind" theme="gray" size="sm" />
					</li>
				</ul>
			</div>

			<div
				v-if="canSnapshot"
				class="space-y-1 border-t border-outline-gray-2 pt-3"
			>
				<Checkbox v-model="takeSnapshot" label="Take a final snapshot first" />
				<p class="text-p-sm text-ink-gray-5">{{ snapshotNote }}</p>
			</div>
		</div>
	</ConfirmDialog>
</template>
