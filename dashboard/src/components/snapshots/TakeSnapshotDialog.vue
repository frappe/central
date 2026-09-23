<script setup lang="ts">
import { call, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API } from '@/api/methods'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSession } from '@/composables/useSession'
import { useSnapshotPricing } from '@/composables/useSnapshots'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { money } from '@/lib/format'
import { snapshotMonthlyCost } from '@/lib/snapshots'

interface TakeSnapshotDialogProps {
	server: VirtualMachineRow | null
}

// A manual snapshot is billed from the moment it is ready, so the price comes before the
// button. Its size is not known until the region finishes, so the disk size is the ceiling.
const props = defineProps<TakeSnapshotDialogProps>()
const emit = defineEmits<{
	'update:server': [value: VirtualMachineRow | null]
	taken: []
}>()

const { activeTeam } = useSession()
const target = computed({
	get: () => props.server,
	set: (value: VirtualMachineRow | null) => emit('update:server', value),
})
const region = computed(() => props.server?.cluster ?? null)
const { rate, currency, freePerServer } = useSnapshotPricing(region)
const title = ref('')
const loading = ref(false)
const error = ref('')

watch(
	() => props.server,
	(server) => {
		title.value = server ? `${server.title || server.resource_id} snapshot` : ''
		error.value = ''
	},
)

const diskGib = computed(() => Math.ceil(props.server?.disk_gigabytes ?? 0))
const ceiling = computed(() =>
	snapshotMonthlyCost(diskGib.value, rate.value, currency.value),
)

async function take(server: VirtualMachineRow) {
	loading.value = true
	error.value = ''
	try {
		await call(API.takeSnapshot, {
			team: activeTeam.value,
			resource_id: server.resource_id,
			title: title.value,
		})
		successToast(
			'Snapshot started. It appears under Snapshots when it is ready.',
		)
		emit('taken')
		target.value = null
	} catch (failure) {
		error.value = getErrorMessage(failure, "The snapshot couldn't be started.")
	} finally {
		loading.value = false
	}
}
</script>

<template>
	<ConfirmDialog
		v-model:target="target"
		title="Take a snapshot"
		confirm-label="Take snapshot"
		size="md"
		:loading="loading"
		:error="error"
		@confirm="take"
	>
		<div class="space-y-3">
			<FormControl v-model="title" label="Name" type="text" />
			<p class="text-p-sm text-ink-gray-7">
				The server keeps running. The snapshot is kept until you delete it. The
				{{ freePerServer }}
				newest snapshots of a server are free.
				<template v-if="ceiling && rate != null">
					An older one costs
					{{ money(rate, currency, { trimTrailingZeros: true }) }}
					per GB per month, at most {{ ceiling }} for this {{ diskGib }} GB
					disk.
				</template>
				<template v-else
					>Snapshot storage has no price in this region yet.</template
				>
			</p>
		</div>
	</ConfirmDialog>
</template>
