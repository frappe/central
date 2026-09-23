<script setup lang="ts">
import { Button, Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useSnapshots } from '@/composables/useSnapshots'
import { formatDate } from '@/lib/format'
import { SNAPSHOT_TYPE_LABEL } from '@/lib/snapshots'
import { errorToast } from '@/lib/toast'

interface ServerSnapshotsCardProps {
	resourceId: string
	/** The viewer holds server:snapshot. */
	canManage: boolean
}

// One server's snapshot summary inside its overview: the daily switch, the newest
// snapshot, and the ways to take or see more.
const props = defineProps<ServerSnapshotsCardProps>()
const emit = defineEmits<{ take: []; viewAll: [] }>()

const {
	snapshots,
	server,
	freePerServer,
	dailyRetentionHours,
	loading,
	error,
	setAutomatic,
	reload,
} = useSnapshots(computed(() => props.resourceId))
const latest = computed(
	() => snapshots.value.find((row) => row.status === 'Available') ?? null,
)
const saving = ref(false)

async function toggle(enabled: boolean) {
	saving.value = true
	try {
		await setAutomatic(props.resourceId, enabled)
	} catch (failure) {
		errorToast(failure)
	} finally {
		saving.value = false
	}
}

defineExpose({ reload })
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<div class="mb-4 flex items-center justify-between gap-3">
			<h3 class="text-base font-semibold text-ink-gray-9">Snapshots</h3>
			<Button variant="ghost" label="View all" @click="emit('viewAll')" />
		</div>

		<p v-if="loading && !server" class="text-p-sm text-ink-gray-5">
			Loading snapshots…
		</p>
		<p v-else-if="error" class="text-p-sm text-ink-red-7">{{ error }}</p>
		<div v-else class="space-y-4">
			<div class="flex items-start justify-between gap-4">
				<div class="min-w-0">
					<p class="text-sm text-ink-gray-9">Daily free snapshot</p>
					<p class="text-p-sm text-ink-gray-5">
						{{ server?.region_automatic
								? `Kept ${dailyRetentionHours} hours, then deleted. The ${freePerServer} newest snapshots of a server are free.`
								: 'This region does not take daily snapshots yet.' }}
					</p>
				</div>
				<Switch
					:model-value="!!server?.automatic"
					:disabled="!canManage || saving || !server?.region_automatic"
					label=""
					aria-label="Daily free snapshot"
					@update:model-value="toggle"
				/>
			</div>

			<p class="text-p-sm text-ink-gray-7">
				<template v-if="latest">
					Latest: {{ latest.title }} ·
					{{ SNAPSHOT_TYPE_LABEL[latest.snapshot_type] }}
					·
					{{ formatDate(latest.creation) }}
				</template>
				<template v-else>No snapshot of this server yet.</template>
			</p>

			<Button
				v-if="canManage"
				icon-left="lucide-camera"
				label="Take snapshot"
				@click="emit('take')"
			/>
		</div>
	</section>
</template>
