<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { ref } from 'vue'
import SSHKeyDialog from '@/components/servers/SSHKeyDialog.vue'
import SSHKeysList from '@/components/servers/SSHKeysList.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamSSHKeys } from '@/composables/useTeamSSHKeys'
import { getErrorMessage, successToast } from '@/lib/feedback'
import type { TeamSSHKey } from '@/types/sshKeys'

const { keys, loading, error, reload, create, rotate, retry, remove } =
	useTeamSSHKeys()
const { canManageSSHKeys } = useCapabilities()
const adding = ref(false)
const rotating = ref<TeamSSHKey | null>(null)
const actionError = ref('')

async function rotateSelected(_title: string, publicKey: string) {
	if (!rotating.value) return
	await rotate(rotating.value.name, publicKey)
	successToast('Key rotation queued for selected servers')
}

async function retrySelected(key: TeamSSHKey) {
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

async function deleteSelected(key: TeamSSHKey) {
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

function closeRotation(open: boolean) {
	if (!open) rotating.value = null
}
</script>

<template>
	<div class="h-full overflow-y-auto">
		<div class="mx-auto w-full max-w-5xl px-6 py-8">
			<Alert v-if="actionError" class="mb-4" theme="red" :title="actionError" />
			<SSHKeysList
				:keys="keys"
				:loading="loading"
				:error="error"
				:can-manage="canManageSSHKeys"
				@add="adding = true"
				@retry-load="reload"
				@retry-sync="retrySelected"
				@rotate="rotating = $event"
				@delete="deleteSelected"
			/>
		</div>
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
