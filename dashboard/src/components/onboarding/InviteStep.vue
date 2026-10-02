<script setup lang="ts">
import { Alert, LoadingText, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import InviteRows, { type InviteRow } from '@/components/team/InviteRows.vue'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { teamParams } from '@/composables/useTeamScope'
import { emailError } from '@/lib/auth'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'

const { roles, loading, error: rolesError } = useTeamRoles()

const inviteCall = useCall<
	string,
	{ team: string; email: string; role: string; resource_type: '*' }
>({
	url: method(API.inviteTeamMember),
	method: 'POST',
	immediate: false,
})

const rows = ref<InviteRow[]>([{ email: '', role: '', error: '' }])
const saving = ref(false)

// Owner is granted by transfer, never by invitation.
const roleOptions = computed(() =>
	roles.value
		.filter((role) => role.role_name !== 'Owner')
		.map((role) => ({ label: role.role_name, value: role.name })),
)
const defaultRole = computed(
	() =>
		roleOptions.value.find((option) => option.label === 'Developer')?.value ??
		roleOptions.value[0]?.value ??
		'',
)
watch(
	defaultRole,
	(role) => {
		for (const row of rows.value) row.role ||= role
	},
	{ immediate: true },
)

const filledRows = computed(() => rows.value.filter((row) => row.email.trim()))
const canSubmit = computed(
	() =>
		filledRows.value.length > 0 && filledRows.value.every((row) => row.role),
)
const submitLabel = computed(() => {
	const count = filledRows.value.length
	if (!count) return 'Send invitations'
	return `Send ${count} ${count === 1 ? 'invitation' : 'invitations'}`
})

// Each row is sent on its own, so one refusal does not stop the others. The rows
// that were sent leave the list, so a second try sends only the failed ones.
async function submit(): Promise<boolean> {
	saving.value = true
	const failed: InviteRow[] = []
	let sent = 0
	for (const row of filledRows.value) {
		row.error = emailError(row.email) || (await sendInvitation(row))
		if (row.error) failed.push(row)
		else sent += 1
	}
	saving.value = false
	if (sent)
		successToast(
			sent === 1 ? 'Invitation sent' : `Invitations sent to ${sent} people`,
		)

	rows.value = failed.length
		? failed
		: [{ email: '', role: defaultRole.value, error: '' }]
	return failed.length === 0
}

// Resolves to the error message, or an empty string once the invitation is sent.
async function sendInvitation(row: InviteRow): Promise<string> {
	const email = row.email.trim().toLowerCase()
	try {
		await submitOrThrow(inviteCall, {
			...teamParams(),
			email,
			role: row.role,
			resource_type: '*',
		})
		return ''
	} catch (exception) {
		return getErrorMessage(exception, "The invitation couldn't be sent.")
	}
}

defineExpose({ canSubmit, submitLabel, saving, submit })
</script>

<template>
	<Alert v-if="rolesError" theme="red" :title="rolesError" />
	<LoadingText v-else-if="loading && !roleOptions.length" :lines="2" />
	<InviteRows
		v-else
		v-model:rows="rows"
		:role-options="roleOptions"
		:default-role="defaultRole"
		:disabled="saving"
	/>
</template>
