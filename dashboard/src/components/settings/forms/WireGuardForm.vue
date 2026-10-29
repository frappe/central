<script setup lang="ts">
import { Badge, Button, Skeleton } from 'frappe-ui'
import { ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Table from '@/components/common/Table.vue'
import WireGuardDeviceDialog from '@/components/wireguard/WireGuardDeviceDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { useWireGuardDevices } from '@/composables/useWireGuardDevices'
import { getErrorMessage, infoToast, successToast } from '@/lib/feedback'
import type { WireGuardDevice } from '@/types/wireguard'

const COLUMNS = [
	{ key: 'title', label: 'Device', class: 'w-full max-w-0' },
	{ key: 'region', label: 'Region' },
	{ key: 'actions', label: '', class: 'w-10 pr-1' },
]

const { devices, regions, servers, loading, error, reload, create, remove } =
	useWireGuardDevices()
const { canManageWireGuard } = useCapabilities()
const { activeTeam } = useSession()

const adding = ref(false)
const viewing = ref<WireGuardDevice | null>(null)
const deleting = ref<WireGuardDevice | null>(null)
const busy = ref(false)
const deleteError = ref('')

// the device lists reset with the team, so close anything that points at the old team
watch(activeTeam, () => {
	adding.value = false
	viewing.value = null
	deleting.value = null
	deleteError.value = ''
})

const regionLabel = (name: string): string =>
	regions.value.find((region) => region.name === name)?.display_name || name

const deleteSelected = async (device: WireGuardDevice): Promise<void> => {
	busy.value = true
	deleteError.value = ''

	try {
		if (await remove(device.name)) successToast(`${device.title} deleted`)
		else infoToast(`${device.title} will be removed once the gateway answers`)
		deleting.value = null
	} catch (failure) {
		deleteError.value = getErrorMessage(
			failure,
			"The device couldn't be deleted.",
		)
	} finally {
		busy.value = false
	}
}

const getActions = (device: WireGuardDevice) => [
	{
		label: 'View settings',
		icon: 'lucide-file-code',
		onClick: () => {
			viewing.value = device
		},
	},
	...(device.can_delete && device.status === 'Active'
		? [
				{
					label: 'Delete',
					icon: 'lucide-trash-2',
					theme: 'red' as const,
					onClick: () => {
						deleteError.value = ''
						deleting.value = device
					},
				},
			]
		: []),
]
</script>

<template>
	<div class="space-y-4 pt-6">
		<Teleport defer to="#settings-actions-wireguard">
			<Button
				v-if="canManageWireGuard && devices.length && regions.length"
				label="Add"
				icon-left="lucide-plus"
				@click="adding = true"
			/>
		</Teleport>

		<EmptyState
			v-if="error"
			icon="lucide-cloud-off"
			title="Devices couldn't load"
			:description="error"
		>
			<template #action>
				<Button label="Retry" @click="reload" />
			</template>
		</EmptyState>

		<div v-else-if="loading && !devices.length" class="space-y-2">
			<Skeleton v-for="n in 3" :key="n" class="h-16 rounded-6" />
		</div>

		<EmptyState
			v-else-if="!devices.length && !regions.length"
			icon="lucide-shield"
			title="WireGuard isn't available yet"
			description="None of your regions has a WireGuard gateway yet."
		/>

		<EmptyState
			v-else-if="!devices.length"
			icon="lucide-shield"
			title="No devices yet"
			description="Add a laptop or phone to reach your servers over their private addresses."
		>
			<template v-if="canManageWireGuard" #action>
				<Button
					label="Add device"
					icon-left="lucide-plus"
					@click="adding = true"
				/>
			</template>
		</EmptyState>

		<Table v-else :columns="COLUMNS" :rows="devices" height="h-auto">
			<template #title="{ row }">
				<div class="space-y-1 py-2">
					<div class="flex items-center gap-2">
						<p class="truncate text-base text-ink-gray-8">{{ row.title }}</p>
						<Badge
							v-if="row.status === 'Removing'"
							theme="orange"
							label="Removing"
						/>
					</div>
					<p class="truncate text-sm text-ink-gray-5">
						{{ row.address }}
						· added by {{ row.added_by_name || row.added_by }}
					</p>
				</div>
			</template>

			<template #region="{ row }">
				<span class="text-base text-ink-gray-7"
					>{{ regionLabel(row.region) }}</span
				>
			</template>

			<template #actions="{ row }">
				<RowActionsMenu :options="getActions(row)" label="Device actions" />
			</template>
		</Table>

		<ConfirmDialog
			v-model:target="deleting"
			:title="`Delete ${deleting?.title ?? ''}?`"
			message="The device loses access to your servers at once."
			confirm-label="Delete"
			theme="red"
			:loading="busy"
			:error="deleteError"
			@confirm="deleteSelected"
		/>

		<WireGuardDeviceDialog
			v-model="adding"
			:regions="regions"
			:servers="servers"
			:save="create"
		/>

		<WireGuardDeviceDialog
			:model-value="!!viewing"
			:saved="viewing"
			:regions="regions"
			:servers="servers"
			:save="create"
			@update:model-value="(open: boolean) => !open && (viewing = null)"
		/>
	</div>
</template>
