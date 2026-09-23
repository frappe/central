<script setup lang="ts">
import { Alert, Button, Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useSnapshots } from '@/composables/useSnapshots'
import { getErrorMessage } from '@/lib/feedback'
import { formatDate } from '@/lib/format'

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
const mutationError = ref('')

async function toggle(enabled: boolean) {
	saving.value = true
	mutationError.value = ''
	try {
		await setAutomatic(props.resourceId, enabled)
	} catch (failure) {
		mutationError.value = getErrorMessage(
			failure,
			"Automatic snapshots couldn't be changed.",
		)
	} finally {
		saving.value = false
	}
}

defineExpose({ reload })
</script>

<template>
	<section class="rounded-7 border border-outline-gray-2 p-5">
		<div class="mb-5 flex items-center justify-between gap-3">
			<h3 class="text-base font-semibold text-ink-gray-9">Snapshots</h3>
			<div class="flex items-center gap-2">
				<Button
					v-if="canManage"
					size="sm"
					icon-left="lucide-camera"
					label="Take snapshot"
					@click="emit('take')"
				/>
				<Button
					size="sm"
					variant="ghost"
					label="View all"
					@click="emit('viewAll')"
				/>
			</div>
		</div>

		<p v-if="loading && !server" class="text-sm text-ink-gray-5">
			Loading snapshots…
		</p>
		<p v-else-if="error" class="text-sm text-ink-red-7">{{ error }}</p>
		<div v-else class="space-y-3.5">
			<Alert v-if="mutationError" theme="red" :title="mutationError" />
			<dl class="space-y-3.5 text-sm">
				<div class="flex items-center justify-between gap-4">
					<dt class="text-ink-gray-5">Latest</dt>
					<dd v-if="latest" class="truncate text-ink-gray-9">
						{{ latest.title }}
						· {{ formatDate(latest.creation) }}
					</dd>
					<dd v-else class="text-ink-gray-5">None yet</dd>
				</div>
				<div class="flex items-center justify-between gap-4">
					<dt class="text-ink-gray-5">Free</dt>
					<dd class="text-ink-gray-9">
						The {{ freePerServer }} newest snapshots
					</dd>
				</div>
				<!-- A region without daily snapshots has nothing to switch. -->
				<div
					v-if="server?.region_automatic"
					class="flex items-center justify-between gap-4"
				>
					<dt class="text-ink-gray-5">
						Daily snapshot
						<span class="text-ink-gray-4"
							>· kept {{ dailyRetentionHours }} hours</span
						>
					</dt>
					<dd>
						<Switch
							:model-value="server.automatic"
							:disabled="!canManage || saving"
							aria-label="Daily snapshot"
							@update:model-value="toggle"
						/>
					</dd>
				</div>
			</dl>
		</div>
	</section>
</template>
