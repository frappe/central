<script setup lang="ts">
import { Alert, Button } from 'frappe-ui'
import { ref } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Table from '@/components/common/Table.vue'
import SSHKeyDialog from '@/components/servers/SSHKeyDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamSSHKeys } from '@/composables/useTeamSSHKeys'
import { getErrorMessage, successToast } from '@/lib/feedback'
import type { TeamSSHKey } from '@/types/sshKeys'

const COLUMNS = [
	{ key: 'title', label: 'Key', class: 'w-full max-w-0' },
	{ key: 'server_count', label: 'Servers' },
	{ key: 'actions', label: '', class: 'w-10 pr-1' },
]

const { keys, loading, error, reload, create, rotate, retry, remove } =
	useTeamSSHKeys()
const { canManageSSHKeys } = useCapabilities()

const adding = ref(false)
const rotating = ref<TeamSSHKey | null>(null)
const actionError = ref('')

const rotateSelected = async (
	_title: string,
	publicKey: string,
): Promise<void> => {
	if (!rotating.value) return

	await rotate(rotating.value.name, publicKey)
	successToast('Key rotation queued for selected servers')
}

const retrySelected = async (key: TeamSSHKey): Promise<void> => {
	actionError.value = ''

	try {
		await retry(key.name)
		successToast(`Retry queued for ${key.title}`)
	} catch (failure) {
		actionError.value = getErrorMessage(
			failure,
			"The key couldn't be synchronized.",
		)
	}
}

const deleteSelected = async (key: TeamSSHKey): Promise<void> => {
	if (
		!confirm(`Delete ${key.title}? It must first be removed from every server.`)
	)
		return

	actionError.value = ''

	try {
		await remove(key.name)
		successToast(`${key.title} deleted`)
	} catch (failure) {
		actionError.value = getErrorMessage(failure, "The key couldn't be deleted.")
	}
}

const getActions = (key: TeamSSHKey) =>
	canManageSSHKeys.value
		? [
				...(key.last_sync_error
					? [
							{
								label: 'Retry sync',
								icon: 'lucide-refresh-cw',
								onClick: () => retrySelected(key),
							},
						]
					: []),
				{
					label: 'Rotate key',
					icon: 'lucide-refresh-cw',
					onClick: () => {
						rotating.value = key
					},
				},
				...(key.server_count
					? []
					: [
							{
								label: 'Delete',
								icon: 'lucide-trash-2',
								theme: 'red' as const,
								onClick: () => deleteSelected(key),
							},
						]),
			]
		: []

const closeRotation = (open: boolean): void => {
	if (!open) rotating.value = null
}
</script>

<template>
	<div class="space-y-4 pt-6">
		<Teleport defer to="#settings-actions-ssh-keys">
			<Button
				v-if="canManageSSHKeys && keys.length"
				label="Add"
				icon-left="lucide-plus"
				@click="adding = true"
			/>
		</Teleport>

		<Alert v-if="actionError" theme="red" :title="actionError" />

		<EmptyState
			v-if="error"
			icon="lucide-cloud-off"
			title="Keys couldn't load"
			:description="error"
		>
			<template #action>
				<Button label="Retry" @click="reload" />
			</template>
		</EmptyState>

		<EmptyState
			v-else-if="!loading && !keys.length"
			icon="lucide-key-round"
			title="No SSH Keys yet"
			description="Add a public key, then use it when you create servers."
		>
			<template v-if="canManageSSHKeys" #action>
				<Button
					label="Add SSH Key"
					icon-left="lucide-plus"
					@click="adding = true"
				/>
			</template>
		</EmptyState>

		<template v-else>
			<Table :columns="COLUMNS" :rows="keys" height="h-auto">
				<template #title="{ row }">
					<div class="space-y-1 py-2">
						<p class="truncate text-base text-ink-gray-8">{{ row.title }}</p>

						<p
							class="truncate font-mono text-sm text-ink-gray-5"
							:title="row.fingerprint"
						>
							{{ row.fingerprint }}
						</p>

						<p
							v-if="row.last_sync_error"
							class="truncate text-sm text-ink-red-6"
						>
							{{ row.last_sync_error }}
						</p>
					</div>
				</template>

				<template #server_count="{ row }">
					<span class="text-base tabular-nums text-ink-gray-7">
						{{ row.server_count }}
					</span>
				</template>

				<template #actions="{ row }">
					<RowActionsMenu :options="getActions(row)" label="SSH Key actions" />
				</template>
			</Table>
		</template>

		<SSHKeyDialog
			v-model="adding"
			:save="create"
			@saved="successToast('SSH Key added')"
		/>

		<SSHKeyDialog
			:model-value="!!rotating"
			:key-to-rotate="rotating"
			:save="rotateSelected"
			@update:model-value="closeRotation"
		/>
	</div>
</template>
