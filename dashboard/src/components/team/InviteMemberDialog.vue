<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useRegions } from '@/composables/useRegions'
import { useSession } from '@/composables/useSession'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { teamParams } from '@/composables/useTeamScope'
import { errorToast, successToast } from '@/lib/toast'
import { teamParams } from '@/composables/useTeamScope'
import { errorToast, successToast } from '@/lib/toast'
import type { ResourceType, TeamRegistry } from '@/types/api'

// Invite a person with a role scoped to all resources or a specific server or
// site. Owner is excluded — Transfer Ownership assigns that. What a role grants
// is browsable on the Roles tab, not repeated here.
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [v: boolean]; invited: [] }>()

const { activeTeam } = useSession()
const { roles } = useTeamRoles()
const { regions } = useRegions()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

const email = ref('')
const role = ref('')
const resource = ref('*::')
const expiresInDays = ref(7)

const registryCall = useCall<TeamRegistry, { team: string }>({
	url: method(API.registry),
	params: teamParams,
	immediate: false,
})

const roleOptions = computed(() =>
	roles.value
		.filter((r) => r.role_name !== 'Owner')
		.map((r) => ({ label: r.role_name, value: r.name })),
)

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
	const assets = registryCall.data?.assets ?? []
	const sites = registryCall.data?.sites ?? []
	return [
		{ label: 'All resources', value: '*::' },
		...assets.map((a) => ({
			label: a.title || a.resource_id,
			value: `Server::${a.name}`,
			description: regionLabel(a.cluster),
		})),
		...sites.map((s) => ({
			label: s.subdomain || s.name,
			value: `Site::${s.name}`,
			description: regionLabel(s.region),
		})),
	]
})

// Reset the form each time the dialog opens.
watch(open, (isOpen) => {
	if (isOpen) {
		email.value = ''
		role.value = ''
		resource.value = '*::'
		expiresInDays.value = 7
		if (!registryCall.data) registryCall.reload()
	}
})

type InviteParams = {
	team: string
	email: string
	role: string
	expires_in_days: number
	resource_type: ResourceType
	resource_name: string | null
}

const inviteCall = useCall<string, InviteParams>({
	url: method(API.inviteTeamMember),
	method: 'POST',
	immediate: false,
})

const canSubmit = computed(
	() => /\S+@\S+\.\S+/.test(email.value) && !!role.value,
)

function parseResource(key: string): {
	resource_type: ResourceType
	resource_name: string | null
} {
	const [type, name] = key.split('::') as [ResourceType, string]
	return { resource_type: type, resource_name: name || null }
}

const dialogOptions = computed(() => ({
	title: 'Invite member',
	size: 'xl' as const,
	actions: [
		{
			label: 'Send invite',
			variant: 'solid' as const,
			loading: inviteCall.loading,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))

async function submit() {
	if (!canSubmit.value) return
	const scope = parseResource(resource.value)
	try {
		await inviteCall.submit({
			team: activeTeam.value!,
			email: email.value.trim().toLowerCase(),
			role: role.value,
			expires_in_days: expiresInDays.value,
			resource_type: scope.resource_type,
			resource_name: scope.resource_name,
		})
		if (inviteCall.error) throw inviteCall.error
		successToast(`Invitation sent to ${email.value.trim().toLowerCase()}`)
		emit('invited')
		open.value = false
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:size="dialogOptions.size"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<div class="space-y-4">
				<FormControl
					v-model="email"
					type="email"
					label="Email"
					placeholder="person@example.com"
					autocomplete="off"
				/>
				<div class="flex items-end gap-2">
					<FormControl v-model="role" type="select" label="Role" :options="roleOptions"
						placeholder="Choose a role"
class="min-w-0 flex-1"
/>
					<span class="mb-1 shrink-0 text-p-sm text-ink-gray-5">on</span>
					<FormControl v-model="resource" type="select" label="Resource" :options="resourceOptions"
						class="min-w-0 flex-1" />
				</div>
				<FormControl
					v-model.number="expiresInDays"
					type="number"
					label="Invitation expires in (days)"
					:min="1"
					:max="30"
				/>
			</div>
		</template>
	</Dialog>
</template>
