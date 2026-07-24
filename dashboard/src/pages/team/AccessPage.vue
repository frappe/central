<script setup lang="ts">
import { computed, ref } from 'vue'
import { Avatar, TabButtons } from 'frappe-ui'
import MembersPanel from '@/components/team/MembersPanel.vue'
import RolesPanel from '@/components/team/RolesPanel.vue'
import { useSession } from '@/composables/useSession'
import { useTeamMembers } from '@/composables/useTeamMembers'

// Members and roles are two views of the same thing — who is on the team and what
// each role grants — so they live on one page behind a tab toggle, sharing one
// identity header (avatar + member count).
const { activeTeamLabel } = useSession()
const { members } = useTeamMembers()

const tab = ref('team')
const tabs = [
	{ label: 'Team', value: 'team' },
	{ label: 'Roles', value: 'roles' },
]

const memberCountText = computed(() => {
	const count = members.value.length
	return `${count} ${count === 1 ? 'member' : 'members'}`
})
</script>

<template>
	<main class="mx-auto flex flex-col max-w-3xl gap-3 mt-10 px-3 xl:p-0">
		<div class="flex items-center gap-2 mb-2">
			<Avatar :label="activeTeamLabel" size="2xl" />
			<div class="leading-relaxed">
				<p class="text-base font-medium text-ink-gray-9">
					{{ activeTeamLabel }}
				</p>
				<p class="text-p-sm text-ink-gray-5">{{ memberCountText }}</p>
			</div>

			<TabButtons :options="tabs" v-model="tab" class="ml-auto my-auto" />
		</div>

		<MembersPanel v-if="tab === 'team'" />
		<RolesPanel v-else />
	</main>
</template>
