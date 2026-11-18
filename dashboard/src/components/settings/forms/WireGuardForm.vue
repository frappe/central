<script setup lang="ts">
import { Badge, Button, Skeleton, TabButtons, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
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

type WireGuardView = 'devices' | 'servers'

const VIEWS: {
	label: string
	value: WireGuardView
	iconLeft: string
	searchLabel: string
}[] = [
	{
		label: 'Devices',
		value: 'devices',
		iconLeft: 'lucide-laptop',
		searchLabel: 'Search devices',
	},
	{
		label: 'Server access',
		value: 'servers',
		iconLeft: 'lucide-shield-check',
		searchLabel: 'Search servers',
	},
]

const view = ref<WireGuardView>('devices')
const queries = ref<Record<WireGuardView, string>>({ devices: '', servers: '' })
const adding = ref(false)
const opened = ref<OpenedWireGuardDevice | null>(null)
const deleting = ref<WireGuardDevice | null>(null)
const busy = ref(false)
const deleteError = ref('')

const activeView = computed(() =>
	VIEWS.find((option) => option.value === view.value),
)

const countLabels = computed<Record<WireGuardView, string>>(() => ({
	devices: devices.value.length ? String(devices.value.length) : '',
	servers: servers.value.length
		? `${servers.value.filter((server) => server.has_wireguard_access).length}/${servers.value.length}`
		: '',
}))

// the device lists reset with the team, so close anything that points at the old team
watch(activeTeam, () => {
	view.value = 'devices'
	queries.value = { devices: '', servers: '' }
	adding.value = false
	opened.value = null
	deleting.value = null
	deleteError.value = ''
})

const regionLabel = (name: string): string =>
	regions.value.find((region) => region.name === name)?.display_name || name

const visibleDevices = computed(() => {
	const query = queries.value.devices.trim().toLowerCase()
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
				v-if="
					view === 'devices' &&
					canManageWireGuard &&
					devices.length &&
					regions.length
				"
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
			<div class="flex flex-wrap items-center justify-between gap-2">
				<TabButtons
					v-model="view"
					:options="VIEWS"
					aria-label="WireGuard VPN sections"
				>
					<template #suffix="{ button }">
						<span
							v-if="countLabels[button.value as WireGuardView]"
							class="text-sm tabular-nums text-ink-gray-5"
						>
							{{ countLabels[button.value as WireGuardView] }}
						</span>
					</template>
				</TabButtons>

				<TextInput
					v-if="countLabels[view]"
					v-model="queries[view]"
					type="search"
					class="w-full sm:w-48"
					:placeholder="activeView?.searchLabel"
					:aria-label="activeView?.searchLabel"
				>
					<template #prefix>
						<span
							class="lucide-search size-4 text-ink-gray-5"
							aria-hidden="true"
						/>
					</template>
				</TextInput>
			</div>

			<div v-if="view === 'devices'" class="space-y-4">
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
					<p
						v-if="!visibleDevices.length"
						class="py-4 text-p-sm text-ink-gray-6"
					>
						No device matches “{{ queries.devices.trim() }}”.
						<button
							type="button"
							class="text-p-sm-medium text-ink-gray-8 underline"
							@click="queries.devices = ''"
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
			</div>

			<div v-else class="space-y-4">
				<p class="text-p-sm text-ink-gray-6">
					Choose which servers your team's devices can reach over WireGuard VPN.
				</p>

				<WireGuardServerList
					v-model:query="queries.servers"
					:regions="regions"
					:servers="servers"
					@changed="reload"
				/>
			</div>
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
