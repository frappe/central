<script setup lang="ts">
import { Avatar, Button, Dropdown } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import MembersPanel from '@/components/team/MembersPanel.vue'
import RenameTeamDialog from '@/components/team/RenameTeamDialog.vue'
import RolesPanel from '@/components/team/RolesPanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { useTeamSettings } from '@/composables/useTeamSettings'

// One Teams surface: roster + roles, with rename beside the title, delete in the
// team overflow, and transfer ownership on member rows — not a separate settings page.
const router = useRouter()
const { activeTeamLabel } = useSession()
const { members } = useTeamMembers()
const { canEditTeam, canDeleteTeam } = useCapabilities()
const { saving, deleteTeam } = useTeamSettings()

const tab = ref('team')
const renameOpen = ref(false)
const deleteTarget = ref<'delete' | null>(null)

const memberCountText = computed(() => {
	const count = members.value.length
	return `${count} ${count === 1 ? 'member' : 'members'}`
})

const teamMenu = computed(() => {
	if (!canDeleteTeam.value) return []
	return [
		{
			label: 'Delete team',
			icon: 'lucide-trash-2',
			theme: 'red' as const,
			onClick: () => {
				deleteTarget.value = 'delete'
			},
		},
	]
})

async function onDelete(): Promise<void> {
	if (await deleteTeam()) {
		deleteTarget.value = null
		router.push('/servers')
	}
}
</script>

<template>
	<main class="relative mx-auto mt-10 flex max-w-3xl flex-col gap-2 px-3 xl:p-0">
		<div class="mb-2 flex items-center gap-3">
			<!-- Square: this is the organisation, not a person. Circles stay
			     reserved for people across the console. -->
			<Avatar :label="activeTeamLabel" size="2xl" shape="square" />
			<div class="min-w-0 flex-1 leading-relaxed">
				<div class="flex items-center gap-0.5">
					<p class="truncate text-base font-medium text-ink-gray-9">
						{{ activeTeamLabel }}
					</p>
					<Button
						v-if="canEditTeam"
						variant="ghost"
						size="xs"
						icon="lucide-pencil"
						aria-label="Rename team"
						@click="renameOpen = true"
					/>
				</div>
				<p class="text-p-sm text-ink-gray-5">{{ memberCountText }}</p>
			</div>

			<Dropdown v-if="teamMenu.length" :options="teamMenu" placement="left">
				<template #trigger>
					<Button
						variant="ghost"
						size="sm"
						icon="lucide-ellipsis"
						aria-label="Team actions"
					/>
				</template>
			</Dropdown>
		</div>

		<MembersPanel v-if="tab === 'team'" v-model:tab="tab" />
		<RolesPanel v-else v-model:tab="tab" />

		<RenameTeamDialog v-model:open="renameOpen" />
		<ConfirmDialog
			v-model:target="deleteTarget"
			title="Delete team"
			:message="`Permanently delete “${activeTeamLabel}”? Servers and sites must be removed first. This can't be undone.`"
			confirm-label="Delete team"
			theme="red"
			:loading="saving"
			@confirm="onDelete"
		/>
	</main>
</template>
