<script setup lang="ts">
import { Alert, Button, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Table from '@/components/common/Table.vue'
import SSHKeyDialog from '@/components/servers/SSHKeyDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
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
const { activeTeam } = useSession()

const adding = ref(false)
const rotating = ref<TeamSSHKey | null>(null)
const actionError = ref('')

const keyQuery = ref('')

watch(activeTeam, () => {
	keyQuery.value = ''
})

const visibleKeys = computed(() => {
	const query = keyQuery.value.trim().toLowerCase()
	if (!query) return keys.value

	return keys.value.filter((key) =>
		[key.title, key.fingerprint].join(' ').toLowerCase().includes(query),
	)
})

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

		<Alert
			v-if="actionError"
			theme="red"
			title="Couldn't update your SSH keys"
			:description="actionError"
		/>

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
			title="No SSH keys yet"
			description="Add a public key, then use it when you create servers."
		>
			<template v-if="canManageSSHKeys" #action>
				<Button
					label="Add SSH key"
					icon-left="lucide-plus"
					@click="adding = true"
				/>
			</template>
		</EmptyState>

		<template v-else>
			<TextInput
				v-if="keys.length"
				v-model="keyQuery"
				type="search"
				placeholder="Search keys"
				aria-label="Search SSH keys"
			>
				<template #prefix>
					<span
						class="lucide-search size-4 text-ink-gray-5"
						aria-hidden="true"
					/>
				</template>
			</TextInput>

			<p
				v-if="keys.length && !visibleKeys.length"
				class="py-4 text-p-sm text-ink-gray-6"
			>
				No key matches “{{ keyQuery.trim() }}”.
				<button
					type="button"
					class="text-p-sm-medium text-ink-gray-8 underline"
					@click="keyQuery = ''"
				>
					Clear search
				</button>
			</p>

			<Table v-else :columns="COLUMNS" :rows="visibleKeys" height="h-auto">
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
					<RowActionsMenu :options="getActions(row)" label="SSH key actions" />
				</template>
			</Table>
		</template>

		<SSHKeyDialog
			v-model="adding"
			:save="create"
			@saved="successToast('SSH key added')"
		/>

		<SSHKeyDialog
			:model-value="!!rotating"
			:key-to-rotate="rotating"
			:save="rotateSelected"
			@update:model-value="closeRotation"
		/>
	</div>
</template>
