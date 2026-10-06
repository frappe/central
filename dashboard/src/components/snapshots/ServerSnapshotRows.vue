<script setup lang="ts">
import { Skeleton, Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useSnapshots } from '@/composables/useSnapshots'
import { getErrorMessage } from '@/lib/feedback'
import { formatDate, plural } from '@/lib/format'

interface ServerSnapshotRowsProps {
	resourceId: string
	/** The viewer holds server:snapshot, so the daily switch is theirs to change. */
	canManage: boolean
}

// Snapshot rows for a server's information list: how many it has, with a way to see them,
// and the daily switch where the region takes daily snapshots.
const props = defineProps<ServerSnapshotRowsProps>()
const emit = defineEmits<{ viewAll: [] }>()

const { snapshots, server, loading, error, setAutomatic } = useSnapshots(
	computed(() => props.resourceId),
)
const ready = computed(() =>
	snapshots.value.filter((row) => row.status === 'Available'),
)
const summary = computed(() => {
	if (!ready.value.length) return 'None yet'
	return `${plural(ready.value.length, 'snapshot')} · latest ${formatDate(ready.value[0].creation)}`
})

const saving = ref(false)
const toggleError = ref('')
async function toggle(enabled: boolean) {
	saving.value = true
	toggleError.value = ''
	try {
		await setAutomatic(props.resourceId, enabled)
	} catch (failure) {
		toggleError.value = getErrorMessage(
			failure,
			"Daily snapshots couldn't be changed.",
		)
	} finally {
		saving.value = false
	}
}
</script>

<template>
	<div class="flex items-center justify-between gap-4">
		<dt class="text-ink-gray-5">Snapshots</dt>
		<dd v-if="loading && !server"><Skeleton class="h-3 w-32 rounded-4" /></dd>
		<dd v-else-if="error" class="text-ink-gray-5">Unavailable</dd>
		<dd v-else>
			<button
				type="button"
				class="flex items-center gap-1 rounded-4 text-ink-gray-9 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-3"
				@click="emit('viewAll')"
			>
				{{ summary }}
				<span
					class="lucide-chevron-right size-3.5 text-ink-gray-5"
					aria-hidden="true"
				/>
			</button>
		</dd>
	</div>
	<!-- Only a region that takes daily snapshots has a switch to show. -->
	<div
		v-if="server?.region_automatic"
		class="flex items-center justify-between gap-4"
	>
		<dt class="text-ink-gray-5">Daily snapshot</dt>
		<dd class="flex items-center gap-2">
			<span v-if="toggleError" class="text-xs text-ink-red-7"
				>{{ toggleError }}</span
			>
			<Switch
				:model-value="server.automatic"
				:disabled="!canManage || saving"
				aria-label="Daily snapshot"
				@update:model-value="toggle"
			/>
		</dd>
	</div>
</template>
