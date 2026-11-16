<script setup lang="ts">
import { Alert, LoadingText } from 'frappe-ui'
import InviteRows from '@/components/team/InviteRows.vue'
import { useBulkInvite } from '@/composables/useBulkInvite'
import { __ } from '@/lib/translate'

// A new team has no servers or sites yet, so every invitation covers the whole team.
const {
	rows,
	roleOptions,
	defaultRole,
	rolesLoading,
	rolesError,
	canSubmit,
	submitLabel,
	saving,
	requestError,
	submit,
} = useBulkInvite()

defineExpose({
	canSubmit,
	submitLabel,
	saving,
	submit: async () => (await submit()).failed === 0,
})

const sendInvitationsErrorTitle = __("Couldn't send the invitations")
const loadRolesErrorTitle = __("Couldn't load the roles")
</script>

<template>
	<Alert
		v-if="requestError"
		class="mb-4"
		theme="red"
		:title="sendInvitationsErrorTitle"
		:description="requestError"
	/>
	<Alert
		v-if="rolesError"
		theme="red"
		:title="loadRolesErrorTitle"
		:description="rolesError"
	/>
	<LoadingText v-else-if="rolesLoading && !roleOptions.length" :lines="2" />
	<InviteRows
		v-else
		v-model:rows="rows"
		:role-options="roleOptions"
		:default-role="defaultRole"
		:disabled="saving"
	/>
</template>
