<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Avatar, Button, Dialog, FormControl, useCall } from 'frappe-ui'
import { API, method } from '@/api/methods'
import { teamParams } from '@/composables/useTeamScope'
import { useRegions } from '@/composables/useRegions'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamRoles } from '@/composables/useTeamRoles'
import type {
	ResourceType,
	TeamMemberRoleAssignment,
	TeamMemberRow,
	TeamRegistry,
} from '@/types/api'

const props = defineProps<{ member: TeamMemberRow | null }>()
const emit = defineEmits<{ 'update:member': [member: TeamMemberRow | null] }>()

const { roles } = useTeamRoles()
const { setRoles } = useTeamMembers()
const { regions } = useRegions()

const regionLabel = (regionName: string | null | undefined): string | undefined => {
	const region = regions.value.find((r) => r.region === regionName)
	if (!region?.display_name) return undefined
	return region.provider
		? `${region.display_name} · ${region.provider}`
		: region.display_name
}

const open = computed({
	get: () => !!props.member,
	set: (v: boolean) => {
		if (!v) emit('update:member', null)
	},
})

const rows = ref<TeamMemberRoleAssignment[]>([])

const registryCall = useCall<TeamRegistry, { team: string }>({
	url: method(API.registry),
	params: teamParams,
	immediate: false,
})

watch(
	() => props.member,
	(member) => {
		if (!member) return
		rows.value = member.roles.map((r) => ({ ...r }))
		if (!registryCall.data) registryCall.reload()
	},
)

const roleOptions = computed(() =>
	roles.value
		.filter((r) => r.role_name !== 'Owner')
		.map((r) => ({ label: r.role_name, value: r.name })),
)

const resourceKey = (type: ResourceType, name: string | null): string =>
	`${type}::${name ?? ''}`

const applyResourceKey = (row: TeamMemberRoleAssignment, key: string): void => {
	const [type, name] = key.split('::') as [ResourceType, string]
	row.resource_type = type
	row.resource_name = name || null
}

const resourceOptions = computed(() => {
	const assets = registryCall.data?.assets ?? []
	const sites = registryCall.data?.sites ?? []
	return [
		{ label: 'All servers', value: resourceKey('All Servers', null) },
		{ label: 'All sites', value: resourceKey('All Sites', null) },
		...assets.map((a) => ({
			label: a.title || a.resource_id,
			value: resourceKey('Server', a.name),
			description: regionLabel(a.cluster),
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
		{ role: '', resource_type: 'All Servers', resource_name: null },
	]
}

const removeRow = (index: number): void => {
	rows.value = rows.value.filter((_, i) => i !== index)
}

const dominatingIndex = computed(() => rows.value.findIndex((r) => r.role === 'Admin'))

const canSubmit = computed(() => rows.value.length > 0 && rows.value.every((r) => r.role))

const submitting = ref(false)

const submit = async (): Promise<void> => {
	if (!canSubmit.value || !props.member) return
	submitting.value = true
	const ok = await setRoles(props.member.user, rows.value)
	submitting.value = false
	if (ok) open.value = false
}

const dialogOptions = computed(() => ({
	title: 'Manage roles',
	size: 'lg' as const,
	actions: [
		{
			label: 'Back',
			variant: 'outline' as const,
			iconLeft: 'lucide-arrow-left',
			onClick: () => {
				open.value = false
			},
		},
		{
			label: 'Save',
			variant: 'solid' as const,
			loading: submitting.value,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:size="dialogOptions.size"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<div v-if="member" class="space-y-4">
				<div class="flex items-center gap-3">
					<Avatar :label="member.full_name" size="md" />
					<div class="min-w-0">
						<p class="truncate font-medium text-ink-gray-9">{{ member.full_name }}</p>
						<p class="truncate text-p-sm text-ink-gray-5">{{ member.user }}</p>
					</div>
				</div>

				<div
					v-if="dominatingIndex !== -1"
					class="flex items-start gap-2 rounded-md border border-outline-gray-2 bg-surface-gray-1 p-3 text-p-sm text-ink-gray-6"
				>
					<span class="lucide-info mt-0.5 size-4 shrink-0" aria-hidden="true" />
					<span>Admin already covers everything, so the roles below stay inactive until you remove it.</span>
				</div>

				<div class="space-y-2">
					<div
						v-for="(row, index) in rows"
						:key="index"
						class="flex items-center gap-2"
						:class="{ 'opacity-50': dominatingIndex !== -1 && index !== dominatingIndex }"
					>
						<FormControl
							type="select"
							v-model="row.role"
							:options="roleOptions"
							placeholder="Choose a role"
							class="min-w-0 flex-1"
						/>
						<span class="shrink-0 text-p-sm text-ink-gray-5">on</span>
						<FormControl
							type="select"
							:model-value="resourceKey(row.resource_type, row.resource_name)"
							:options="resourceOptions"
							class="min-w-0 flex-1"
							@update:model-value="applyResourceKey(row, $event as string)"
						/>
						<Button
							variant="ghost"
							icon="lucide-x"
							aria-label="Remove role"
							@click="removeRow(index)"
						/>
					</div>
				</div>

				<Button
					variant="subtle"
					icon-left="lucide-plus"
					label="Add role for a resource"
					@click="addRow"
				/>
			</div>
		</template>
	</Dialog>
</template>
