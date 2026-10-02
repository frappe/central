<script setup lang="ts">
import { Alert, LoadingText } from 'frappe-ui'
import InviteRows from '@/components/team/InviteRows.vue'
import { useBulkInvite } from '@/composables/useBulkInvite'

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
</script>

<template>
	<Alert v-if="requestError" class="mb-4" theme="red" :title="requestError" />
	<Alert v-if="rolesError" theme="red" :title="rolesError" />
	<LoadingText v-else-if="rolesLoading && !roleOptions.length" :lines="2" />
	<InviteRows
		v-else
		v-model:rows="rows"
		:role-options="roleOptions"
		:default-role="defaultRole"
		:disabled="saving"
	/>
</template>
