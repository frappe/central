<script setup lang="ts">
import {
	Avatar,
	Breadcrumbs,
	Button,
	PageHeader,
	PageHeaderMobile,
	TabButtons,
} from 'frappe-ui'
import { computed, ref } from 'vue'
import NavDrawerTitle from '@/components/navigation/NavDrawerTitle.vue'
import MembersPanel from '@/components/team/MembersPanel.vue'
import RolesPanel from '@/components/team/RolesPanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { openSettings } from '@/composables/useSettings'
import { useTeamMembers } from '@/composables/useTeamMembers'

// Members and roles are two views of the same thing — who is on the team and what
// each role grants — so they live on one page behind a tab toggle, sharing one
// identity header. The Team/Roles switcher rides on the list's own controls
// row, ahead of search; each tab keeps its primary action (Invite, New role)
// in that row's toolbar. Team-level settings (logo, rename, delete) open from
// the pencil, on the Team tab of the shared settings dialog.
const { activeTeamLabel, activeTeamLogo } = useSession()
const { members } = useTeamMembers()
const { canEditTeam, canDeleteTeam } = useCapabilities()

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
	<PageHeaderMobile class="sm:hidden">
		<NavDrawerTitle title="Team" />
	</PageHeaderMobile>

	<PageHeader class="hidden sm:flex">
		<Breadcrumbs :items="[{ label: 'Team', route: { name: 'Members' } }]" />
	</PageHeader>

	<!-- The pane and its overflow are desktop-only: on a phone the shell owns the
	     scroll, and a second scroll box inside it would swallow the tap-the-tab-
	     to-scroll-top gesture and hide the last rows behind the nav bar. -->
	<div class="sm:flex sm:h-full sm:min-h-0">
		<div class="sm:min-w-0 sm:flex-1 sm:overflow-y-auto">
			<main class="mx-auto flex flex-col max-w-3xl gap-3 mt-10 px-3 xl:p-0">
				<div class="mb-5 flex items-center gap-3">
					<!-- Square: this is the organisation, not a person. Circles stay
					     reserved for people across the console. -->
					<Avatar
						:image="activeTeamLogo ?? undefined"
						:label="activeTeamLabel"
						size="2xl"
						shape="square"
					/>
					<div>
						<p class="text-lg font-semibold text-ink-gray-9">
							{{ activeTeamLabel }}
						</p>
						<p class="mt-0.5 text-p-base text-ink-gray-5">{{ memberCountText }}</p>
					</div>

					<!-- Icon-only: renaming/deleting the team is rare — a label would
					     outweigh the action. -->
					<Button
						v-if="canEditTeam || canDeleteTeam"
						class="ml-auto my-auto"
						variant="subtle"
						icon="lucide-pencil"
						label="Edit team"
						@click="openSettings('team-settings')"
					/>
				</div>

				<MembersPanel v-if="tab === 'team'">
					<template #controls-start>
						<TabButtons :options="tabs" v-model="tab" />
					</template>
				</MembersPanel>
				<RolesPanel v-else>
					<template #controls-start>
						<TabButtons :options="tabs" v-model="tab" />
					</template>
				</RolesPanel>
			</main>
		</div>

		<!-- RoleCapabilitiesPanel teleports here: the panel is opened from a row
		     deep inside `main`, but it has to dock beside that scroll box rather
		     than inside it. `contents` keeps the panel itself the flex item, so its
		     24rem and the slide's negative margin measure against this row. -->
		<div id="team-page-aside" class="contents" />
	</div>
</template>
