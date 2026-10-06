<script setup lang="ts">
import { computed } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { money } from '@/lib/format'
import type { VMSnapshotRow } from '@/types/snapshots'

interface KeepSnapshotDialogProps {
	target: VMSnapshotRow | null
	/** Price per GB-month in the snapshot's region. Null when the region has no price. */
	rate: number | null
	currency: string
	freePerServer: number
	loading?: boolean
	error?: string
}

// A kept snapshot can start to cost money later, so the dialog names the amount and
// when it applies before the customer confirms.
const props = defineProps<KeepSnapshotDialogProps>()
const emit = defineEmits<{
	'update:target': [value: VMSnapshotRow | null]
	confirm: [value: VMSnapshotRow]
}>()

const target = computed({
	get: () => props.target,
	set: (value: VMSnapshotRow | null) => emit('update:target', value),
})
const format = (amount: number) =>
	money(amount, props.currency, { trimTrailingZeros: true })
const monthly = computed(() =>
	props.target && props.rate != null
		? props.target.size_gib * props.rate
		: null,
)
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		title="Keep this snapshot"
		confirm-label="Keep snapshot"
		:loading="loading"
		:error="error"
		size="md"
		@confirm="emit('confirm', $event)"
	>
		<p v-if="target" class="text-p-base text-ink-gray-7">
			<span class="font-semibold text-ink-gray-9">{{ target.title }}</span>
			is no longer deleted on its own. It stays free while it is one of this
			server's
			{{ freePerServer }}
			newest snapshots.
			<template v-if="monthly != null">
				After that it costs
				<span class="font-semibold text-ink-gray-9"
					>{{ format(monthly) }}
					per month</span
				>
				({{ target.size_gib }}
				GB × {{ format(rate ?? 0) }} per GB) until you delete it.
			</template>
			<template v-else
				>Snapshot storage has no price in this region yet.</template
			>
		</p>
	</ConfirmDialog>
</template>
