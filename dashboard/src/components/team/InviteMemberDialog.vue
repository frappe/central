<script setup lang="ts">
import { Alert, Button, Dialog, LoadingText, useCall } from 'frappe-ui'
import { computed, watch } from 'vue'
import { API, method } from '@/api/methods'
import InviteRows from '@/components/team/InviteRows.vue'
import { ALL_RESOURCES, useBulkInvite } from '@/composables/useBulkInvite'
import { useRegions } from '@/composables/useRegions'
import { teamParams } from '@/composables/useTeamScope'
import type { TeamRegistry } from '@/types/api'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [v: boolean]; invited: [] }>()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

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
	reset,
	submit,
} = useBulkInvite()
const { regions } = useRegions()

const registryCall = useCall<TeamRegistry, { team: string }>({
	url: method(API.registry),
	params: teamParams,
	immediate: false,
})

const regionLabel = (
	regionName: string | null | undefined,
): string | undefined => {
	const region = regions.value.find((r) => r.region === regionName)
	if (!region?.display_name) return undefined
	return region.provider
		? `${region.display_name} · ${region.provider}`
		: region.display_name
}

const resourceOptions = computed(() => {
	const servers = registryCall.data?.servers ?? []
	const sites = registryCall.data?.sites ?? []
	return [
		{ label: 'All resources', value: ALL_RESOURCES },
		...servers.map((a) => ({
			label: a.title || a.resource_id,
			value: `Server::${a.name}`,
			description: regionLabel(a.region),
		})),
		...sites.map((s) => ({
			label: s.subdomain || s.name,
			value: `Site::${s.name}`,
			description: regionLabel(s.region),
		})),
	]
})

// Read the servers and sites on every open, so a resource created since is offered.
watch(open, (isOpen) => {
	if (!isOpen) return
	reset()
	registryCall.reload()
})

// A partly failed batch stays open on the failed rows, and the sent ones still
// refresh the invitation list behind the dialog.
async function send(): Promise<void> {
	const { sent, failed } = await submit()
	if (sent) emit('invited')
	if (!failed) open.value = false
}
</script>

<template>
	<Dialog v-model="open" title="Invite members" size="2xl">
		<template #default>
			<Alert
				v-if="requestError"
				class="mb-4"
				theme="red"
				:title="requestError"
			/>
			<Alert v-if="rolesError" theme="red" :title="rolesError" />
			<LoadingText v-else-if="rolesLoading && !roleOptions.length" :lines="2" />
			<InviteRows
				v-else
				v-model:rows="rows"
				:role-options="roleOptions"
				:resource-options="resourceOptions"
				:default-role="defaultRole"
				:disabled="saving"
			/>
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button label="Cancel" :disabled="saving" @click="open = false" />
				<Button
					variant="solid"
					:label="submitLabel"
					:loading="saving"
					:disabled="!canSubmit"
					@click="send"
				/>
			</div>
		</template>
	</Dialog>
</template>
