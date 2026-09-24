<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DeleteSnapshotsDialog from '@/components/snapshots/DeleteSnapshotsDialog.vue'
import KeepSnapshotDialog from '@/components/snapshots/KeepSnapshotDialog.vue'
import SnapshotListView from '@/components/snapshots/SnapshotListView.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSnapshots } from '@/composables/useSnapshots'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { plural } from '@/lib/format'
import type { VMSnapshotRow } from '@/types/snapshots'

const router = useRouter()
const route = useRoute()
const initialSearch =
	typeof route.query.search === 'string' ? route.query.search : ''
const { canSnapshotServer } = useCapabilities()
const {
	snapshots,
	currency,
	rates,
	freePerServer,
	loading,
	error,
	reload,
	keep,
	remove,
} = useSnapshots()

const pendingKeep = ref<VMSnapshotRow | null>(null)
const keepBusy = ref(false)
const keepError = ref('')
async function confirmKeep(row: VMSnapshotRow) {
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
async function confirmDelete(rows: VMSnapshotRow[]) {
	deleteBusy.value = true
	deleteError.value = ''
	try {
		const result = await remove(rows.map((row) => row.name))
		const failed = Object.values(result.failed)
		if (result.deleted.length)
			successToast(`${plural(result.deleted.length, 'snapshot')} deleted`)
		if (failed.length) {
			// Keep only the ones that failed on screen, with the region's reason.
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

function restore(row: VMSnapshotRow) {
	router.push({
		path: '/servers/new',
		query: { region: row.region, snapshot: row.name },
	})
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div class="mx-auto w-full max-w-5xl px-6 py-8">
			<SnapshotListView
				:snapshots="snapshots"
				:loading="loading && !snapshots.length"
				:error="error"
				:currency="currency"
				:can-manage="canSnapshotServer"
				:free-per-server="freePerServer"
				:initial-search="initialSearch"
				@retry="reload"
				@keep="(row) => { keepError = ''; pendingKeep = row }"
				@delete="(rows) => { deleteError = ''; pendingDelete = rows }"
				@restore="restore"
			/>
		</div>

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
