<script setup lang="ts">
import { Badge, Button, Skeleton, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import Table from '@/components/common/Table.vue'
import AddWireGuardDeviceDialog from '@/components/wireguard/AddWireGuardDeviceDialog.vue'
import WireGuardDeviceAddedDialog from '@/components/wireguard/WireGuardDeviceAddedDialog.vue'
import WireGuardServerList from '@/components/wireguard/WireGuardServerList.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { useWireGuardDevices } from '@/composables/useWireGuardDevices'
import { getErrorMessage, infoToast, successToast } from '@/lib/feedback'
import { downloadConfig, PRIVATE_KEY_PLACEHOLDER } from '@/lib/wireguard'
import type { OpenedWireGuardDevice, WireGuardDevice } from '@/types/wireguard'

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
const opened = ref<OpenedWireGuardDevice | null>(null)
const deleting = ref<WireGuardDevice | null>(null)
const busy = ref(false)
const deleteError = ref('')

// the device lists reset with the team, so close anything that points at the old team
watch(activeTeam, () => {
	adding.value = false
	opened.value = null
	deleting.value = null
	deleteError.value = ''
})

const regionLabel = (name: string): string =>
	regions.value.find((region) => region.name === name)?.display_name || name

const deviceQuery = ref('')
const isDeviceSearchable = computed(() => devices.value.length > 6)
const visibleDevices = computed(() => {
	const query = deviceQuery.value.trim().toLowerCase()
	if (!query) return devices.value

	return devices.value.filter((device) =>
		[
			device.title,
			device.address,
			device.added_by_name,
			regionLabel(device.region),
		]
			.join(' ')
			.toLowerCase()
			.includes(query),
	)
})

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
		label: 'Download .conf',
		icon: 'lucide-download',
		onClick: () => {
			downloadConfig(device, '')
			infoToast(
				`Replace ${PRIVATE_KEY_PLACEHOLDER} in the file with the private key of ${device.title}, then import it.`,
			)
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
			title="WireGuard VPN isn't available yet"
			description="None of your regions has a WireGuard VPN gateway yet."
		/>

		<template v-else>
			<SettingsSection title="Devices">
				<EmptyState
					v-if="!devices.length"
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

				<template v-else>
					<TextInput
						v-if="isDeviceSearchable"
						v-model="deviceQuery"
						type="search"
						placeholder="Search devices"
						aria-label="Search devices"
					>
						<template #prefix>
							<span
								class="lucide-search size-4 text-ink-gray-5"
								aria-hidden="true"
							/>
						</template>
					</TextInput>

					<p
						v-if="!visibleDevices.length"
						class="py-4 text-p-sm text-ink-gray-6"
					>
						No device matches “{{ deviceQuery.trim() }}”.
						<button
							type="button"
							class="text-p-sm-medium text-ink-gray-8 underline"
							@click="deviceQuery = ''"
						>
							Clear search
						</button>
					</p>

					<Table
						v-else
						:columns="COLUMNS"
						:rows="visibleDevices"
						height="h-auto"
					>
						<template #title="{ row }">
							<div class="space-y-1 py-2">
								<div class="flex items-center gap-2">
									<p class="truncate text-base text-ink-gray-8">
										{{ row.title }}
									</p>
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
							<RowActionsMenu
								:options="getActions(row)"
								label="Device actions"
							/>
						</template>
					</Table>
				</template>
			</SettingsSection>

			<SettingsSection
				title="Servers"
				description="Turn on WireGuard VPN for a server to let your team's devices reach its private address."
			>
				<WireGuardServerList
					:regions="regions"
					:servers="servers"
					@changed="reload"
				/>
			</SettingsSection>
		</template>

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

		<AddWireGuardDeviceDialog
			v-model="adding"
			:regions="regions"
			:save="create"
			@added="(device, privateKey) => (opened = { device, privateKey })"
		/>

		<WireGuardDeviceAddedDialog v-model:target="opened" />
	</div>
</template>
