<script setup lang="ts">
import { Alert, Avatar, Button, Dialog, Select, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useRegions } from '@/composables/useRegions'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { teamParams } from '@/composables/useTeamScope'
import { getErrorMessage } from '@/lib/feedback'
import { splitClientAccess } from '@/lib/resourceScope'
import type {
	ResourceType,
	TeamMemberRoleAssignment,
	TeamMemberRow,
	TeamRegistry,
} from '@/types/api'

interface Props {
	member: TeamMemberRow | null
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })

const { roles } = useTeamRoles()
const { setRoles } = useTeamMembers()
const { regions } = useRegions()
const { activeTeamLabel, isPartnerTeam } = useSession()

const regionLabel = (
	regionName: string | null | undefined,
): string | undefined => {
	const region = regions.value.find((r) => r.region === regionName)
	if (!region?.display_name) return undefined
	return region.provider
		? `${region.display_name} · ${region.provider}`
		: region.display_name
}

const rows = ref<TeamMemberRoleAssignment[]>([])
const NO_CLIENT_ACCESS = 'none'
const clientRole = ref(NO_CLIENT_ACCESS)

const registryCall = useCall<TeamRegistry, { team: string }>({
	url: method(API.registry),
	params: teamParams,
	immediate: false,
})

watch(open, (isOpen) => {
	if (!isOpen || !props.member) return
	const { teamRoles, clientRole: role } = splitClientAccess(props.member.roles)
	rows.value = teamRoles.map((r) => ({ ...r }))
	clientRole.value = role ?? NO_CLIENT_ACCESS
	if (!registryCall.data) registryCall.reload()
})

const roleOptions = computed(() =>
	roles.value
		.filter((r) => r.role_name !== 'Owner')
		.map((r) => ({ label: r.role_name, value: r.name })),
)

// Admin's team capabilities never reach a client, so it would read as more than it gives.
const clientRoleOptions = computed(() => [
	{ label: 'No client access', value: NO_CLIENT_ACCESS },
	...roleOptions.value.filter((option) => option.value !== 'Admin'),
])

const clientGrants = (): TeamMemberRoleAssignment[] =>
	isPartnerTeam.value && clientRole.value !== NO_CLIENT_ACCESS
		? [
				{
					role: clientRole.value,
					resource_type: 'Clients',
					resource_name: null,
				},
			]
		: []

const resourceKey = (
	type: TeamMemberRoleAssignment['resource_type'],
	name: string | null,
): string => `${type}::${name ?? ''}`

const applyResourceKey = (row: TeamMemberRoleAssignment, key: string): void => {
	const [type, name] = key.split('::') as [ResourceType, string]
	row.resource_type = type
	row.resource_name = name || null
}

const resourceOptions = computed(() => {
	const servers = registryCall.data?.servers ?? []
	const sites = registryCall.data?.sites ?? []
	return [
		{ label: 'All resources', value: resourceKey('*', null) },
		...servers.map((a) => ({
			label: a.title || a.resource_id,
			value: resourceKey('Server', a.name),
			description: regionLabel(a.region),
		})),
		...sites.map((s) => ({
			label: s.subdomain || s.name,
			value: resourceKey('Site', s.name),
			description: regionLabel(s.region),
		})),
	]
})

const addRow = (): void => {
	rows.value = [
		...rows.value,
		{ role: '', resource_type: '*', resource_name: null },
	]
}

const removeRow = (index: number): void => {
	rows.value = rows.value.filter((_, i) => i !== index)
}

const dominatingIndex = computed(() =>
	rows.value.findIndex((r) => r.role === 'Admin'),
)

const shadowedIndexes = computed(() => {
	const wildcardRoles = new Set(
		rows.value
			.filter((r) => r.role && r.resource_type === '*')
			.map((r) => r.role),
	)
	return new Set(
		rows.value
			.map((row, index) => ({ row, index }))
			.filter(
				({ row }) => row.resource_type !== '*' && wildcardRoles.has(row.role),
			)
			.map(({ index }) => index),
	)
})

const canSubmit = computed(
	() => rows.value.length > 0 && rows.value.every((r) => r.role),
)

const submitting = ref(false)
const formError = ref('')
watch([rows, clientRole], () => (formError.value = ''), { deep: true })

const submit = async (): Promise<void> => {
	if (!canSubmit.value || !props.member) return
	submitting.value = true
	const grants = [
		...rows.value.filter((_, index) => !shadowedIndexes.value.has(index)),
		...clientGrants(),
	]
	try {
		await setRoles(props.member.user, grants, { throwOnError: true })
		open.value = false
	} catch (e) {
		formError.value = getErrorMessage(
			e,
			"The member's access couldn't be saved.",
		)
	} finally {
		submitting.value = false
	}
}

const dialogOptions = computed(() => ({
	size: 'lg' as const,
	actions: [
		{
			label: 'Add role',
			onClick: addRow,
			class: 'mr-auto',
			iconLeft: 'lucide-plus',
		},
		{
			label: 'Save',
			variant: 'solid' as const,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		title="Manage access"
		:size="dialogOptions.size"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<div class="space-y-4">
				<Alert v-if="formError" theme="red" :title="formError" />
				<div class="flex items-center gap-3">
					<Avatar :label="member?.full_name" size="2xl" />
					<div class="min-w-0">
						<p class="truncate text-base-medium text-ink-gray-9">
							{{ member?.full_name }}
						</p>
						<p class="truncate text-p-sm text-ink-gray-5">
							{{ member?.user }}
						</p>
					</div>
				</div>

				<p class="text-p-sm text-ink-gray-5">
					Assign roles to specific servers or sites, or to all resources.
				</p>

				<Alert
					v-if="dominatingIndex !== -1"
					theme="blue"
					title="Admin already covers everything"
				/>

				<Alert
					v-if="shadowedIndexes.size"
					theme="blue"
					title="A role on all resources already covers the rest"
				/>

				<div class="space-y-2">
					<div
						v-for="(row, index) in rows"
						:key="index"
						class="flex items-center gap-2"
						:class="{ 'opacity-50': dominatingIndex !== -1 && index !== dominatingIndex }"
					>
						<Select
							v-model="row.role"
							:options="roleOptions"
							placeholder="Choose a role"
							class="min-w-0 flex-1"
						/>
						<span class="shrink-0 text-p-sm text-ink-gray-5">on</span>
						<Select
							:model-value="resourceKey(row.resource_type, row.resource_name)"
							:options="resourceOptions"
							class="min-w-0 flex-1"
							@update:model-value="applyResourceKey(row, $event as string)"
						/>
						<Button
							variant="ghost"
							icon="lucide-x"
							label="Remove role"
							@click="removeRow(index)"
						/>
					</div>
				</div>

				<div v-if="isPartnerTeam" class="space-y-2 border-t pt-4">
					<div>
						<p class="text-base-medium text-ink-gray-8">Client access</p>
						<p class="text-p-sm text-ink-gray-5">
							What they can do for every client that gave {{ activeTeamLabel }}
							access. A client never gets more than the Partner role.
						</p>
					</div>
					<Select
						v-model="clientRole"
						:options="clientRoleOptions"
						aria-label="Client access"
					/>
				</div>
			</div>
		</template>
	</Dialog>
</template>
