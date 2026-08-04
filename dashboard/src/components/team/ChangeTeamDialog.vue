<script setup lang="ts">
import { Avatar, Button, Dialog } from 'frappe-ui'
import { ref } from 'vue'
import { useSession } from '@/composables/useSession'
import type { Team } from '@/types/api'
import CreateTeamDialog from './CreateTeamDialog.vue'

const open = defineModel<boolean>('open')

const { teams, activeTeam, setActiveTeam } = useSession()

const selectTeam = (team: Team) => {
	setActiveTeam(team.name)
	open.value = false
}

const createTeamOpen = ref(false)
const createTeam = () => {
	open.value = false
	createTeamOpen.value = true
}
</script>

<template>
	<Dialog
		v-model="open"
		title="Change team"
		message="Switch to another team you belong to."
	>
		<template #default>
			<button
				v-for="team in teams"
				:key="team.name"
				type="button"
				class="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left duration-150 ease-in-out"
				:class="
						team.name === activeTeam
							? 'border border-outline-gray-2 bg-surface-gray-2'
							: 'border border-transparent hover:bg-surface-gray-2'
					"
				@click="selectTeam(team)"
			>
				<Avatar :label="team.label" size="lg" shape="square" />

				<div class="min-w-0 flex-1">
					<div class="truncate text-base font-medium text-ink-gray-8">
						{{ team.label }}
					</div>
					<div v-if="team.name === activeTeam" class="text-sm text-ink-gray-5">
						Current team
					</div>
				</div>

				<span
					v-if="team.name === activeTeam"
					class="lucide-check size-4 shrink-0 text-ink-gray-7"
				/>
			</button>

			<Button
				class="mt-4 w-full justify-center"
				icon-left="lucide-plus"
				label="Create team"
				@click="createTeam"
			/>
		</template>
	</Dialog>

	<CreateTeamDialog v-model:open="createTeamOpen" />
</template>
