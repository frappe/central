<script setup lang="ts">
import { Alert, Button, SettingsRow } from 'frappe-ui'
import { computed, onMounted, ref, watch } from 'vue'
import DeleteAccountDialog from '@/components/settings/DeleteAccountDialog.vue'
import { useAccountDeletion } from '@/composables/useAccountDeletion'
import { useAuth } from '@/composables/useAuth'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { formatDate } from '@/lib/format'

const { currentUser } = useAuth()
const { request, saving, reload, deleteAccount, cancel } = useAccountDeletion()

const target = ref<string | null>(null)
const error = ref('')
watch(target, () => (error.value = ''))
onMounted(reload)

const description = computed(() => {
	if (!request.value) {
		return 'Delete your account and your personal data. Teams you own are archived.'
	}
	if (request.value.status === 'Pending Verification') {
		return 'Confirm with the link we emailed you. Nothing is deleted until you do.'
	}
	return `Your account will be deleted on ${formatDate(request.value.delete_after)}.`
})

async function onDelete(): Promise<void> {
	try {
		await deleteAccount(currentUser.value!)
		target.value = null
		successToast('Check your email to confirm')
	} catch (e) {
		error.value = getErrorMessage(e, "We couldn't start the deletion.")
	}
}

async function onCancel(): Promise<void> {
	error.value = ''
	try {
		await cancel()
		successToast('Account deletion cancelled')
	} catch (e) {
		error.value = getErrorMessage(e, "We couldn't cancel the deletion.")
	}
}
</script>

<template>
	<div class="border-t border-outline-gray-1">
		<Alert v-if="error && !target" class="mt-3" theme="red" :title="error" />
		<SettingsRow title="Delete account" :description="description">
			<Button
				v-if="request"
				label="Cancel deletion"
				:loading="saving"
				@click="onCancel"
			/>
			<Button v-else theme="red" label="Delete" @click="target = currentUser" />
		</SettingsRow>

		<DeleteAccountDialog
			v-model:target="target"
			:deleting="saving"
			:error="error"
			@delete="onDelete"
		/>
	</div>
</template>
