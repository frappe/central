<script setup lang="ts">
import { Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import DeleteSnapshotsDialog from '@/components/snapshots/DeleteSnapshotsDialog.vue'
import KeepSnapshotDialog from '@/components/snapshots/KeepSnapshotDialog.vue'
import SelectSnapshotServerDialog from '@/components/snapshots/SelectSnapshotServerDialog.vue'
import SnapshotListView from '@/components/snapshots/SnapshotListView.vue'
import TakeSnapshotDialog from '@/components/snapshots/TakeSnapshotDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerMapData } from '@/composables/useServerMapData'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useSnapshots } from '@/composables/useSnapshots'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import { plural } from '@/lib/format'
import type { VMSnapshotRow } from '@/types/snapshots'

interface Props {
	server?: VirtualMachineRow
	initialSearch?: string
}

const props = defineProps<Props>()

const router = useRouter()
const { canSnapshotServer, canCreateServer } = useCapabilities()

const {
	servers,
	loading: serversLoading,
	error: serversError,
	reload: reloadServers,
} = useServerMapData()

const {
	snapshots,
	server: setting,
	currency,
	rates,
	freePerServer,
	dailyRetentionHours,
	loading,
	error,
	reload,
	keep,
	remove,
	setAutomatic,
} = useSnapshots(
	props.server ? computed(() => props.server?.resource_id ?? null) : undefined,
)

const canManage = computed(() =>
	props.server
		? !!props.server.capabilities?.includes('server:snapshot')
		: canSnapshotServer.value,
)

const eligibleServers = computed(() =>
	servers.value.filter((server) =>
		['Running', 'Stopped', 'Paused'].includes(server.status ?? ''),
	),
)

const selectingServer = ref(false)
const pendingSnapshot = ref<VirtualMachineRow | null>(null)

const take = (): void => {
	if (props.server) {
		pendingSnapshot.value = props.server
		return
	}

	selectingServer.value = true
}

const savingAutomatic = ref(false)

const automaticDescription = computed(
	() =>
		`Take a snapshot every day. Each one is kept for ${plural(dailyRetentionHours.value, 'hour')} unless you keep it.`,
)

const toggleAutomatic = async (enabled: boolean): Promise<void> => {
	if (!props.server) return

	savingAutomatic.value = true

	try {
		await setAutomatic(props.server.resource_id, enabled)
	} catch (failure) {
		reportError(failure, { title: "Daily snapshots couldn't be changed" })
	} finally {
		savingAutomatic.value = false
	}
}

const pendingKeep = ref<VMSnapshotRow | null>(null)
const keepBusy = ref(false)
const keepError = ref('')

const confirmKeep = async (row: VMSnapshotRow): Promise<void> => {
	keepBusy.value = true
	keepError.value = ''

	try {
		await keep(row.name)
		successToast(`${row.title} is kept`)
		pendingKeep.value = null
	} catch (failure) {
		keepError.value = getErrorMessage(failure, "The snapshot couldn't be kept.")
	} finally {
		keepBusy.value = false
	}
}

const pendingDelete = ref<VMSnapshotRow[] | null>(null)
const deleteBusy = ref(false)
const deleteError = ref('')

const confirmDelete = async (rows: VMSnapshotRow[]): Promise<void> => {
	deleteBusy.value = true
	deleteError.value = ''

	try {
		const result = await remove(rows.map((row) => row.name))
		const failed = Object.values(result.failed)

		if (result.deleted.length)
			successToast(`${plural(result.deleted.length, 'snapshot')} deleted`)

		if (failed.length) {
			pendingDelete.value = rows.filter((row) => row.name in result.failed)
			deleteError.value = failed.join(' ')
		} else pendingDelete.value = null
	} catch (failure) {
		deleteError.value = getErrorMessage(
			failure,
			"The snapshots couldn't be deleted.",
		)
	} finally {
		deleteBusy.value = false
	}
}

const restore = (row: VMSnapshotRow): void => {
	router.push({
		path: '/servers/new',
		query: { region: row.region, snapshot: row.name },
	})
}
</script>

<template>
	<div class="space-y-4">
		<Switch
			v-if="setting?.region_automatic"
			:model-value="setting.automatic"
			:disabled="!canManage || savingAutomatic"
			label="Daily snapshots"
			:description="automaticDescription"
			class="rounded-6 bg-surface-gray-1 px-4 py-3"
			@update:model-value="toggleAutomatic"
		/>

		<SnapshotListView
			:snapshots="snapshots"
			:loading="loading && !snapshots.length"
			:error="error"
			:currency="currency"
			:can-manage="canManage"
			:can-restore="canCreateServer && canManage"
			:free-per-server="freePerServer"
			:initial-search="initialSearch"
			:server-scoped="!!server"
			@retry="reload"
			@keep="(row) => { keepError = ''; pendingKeep = row }"
			@delete="(rows) => { deleteError = ''; pendingDelete = rows }"
			@restore="restore"
			@take="take"
		/>

		<SelectSnapshotServerDialog
			v-if="!server"
			v-model="selectingServer"
			:servers="eligibleServers"
			:loading="serversLoading"
			:error="serversError"
			@retry="reloadServers"
			@selected="pendingSnapshot = $event"
		/>

		<TakeSnapshotDialog v-model:server="pendingSnapshot" @taken="reload" />

		<KeepSnapshotDialog
			v-model:target="pendingKeep"
			:rate="pendingKeep ? (rates[pendingKeep.region] ?? null) : null"
			:currency="currency"
			:free-per-server="freePerServer"
			:loading="keepBusy"
			:error="keepError"
			@confirm="confirmKeep"
		/>

		<DeleteSnapshotsDialog
			v-model:target="pendingDelete"
			:loading="deleteBusy"
			:error="deleteError"
			@confirm="confirmDelete"
		/>
	</div>
</template>
