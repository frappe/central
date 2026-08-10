<script setup lang="ts">
import { Avatar, Dialog, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import type { Team } from '@/types/api'
import CreateTeamDialog from './CreateTeamDialog.vue'

// The team switcher. Every row carries the same two lines — name, then your
// standing in it — so the list keeps one rhythm and the check alone says where
// you are. "Create team" is the last row rather than a button below the list:
// same shape, so it reads as one more place you could go.
const open = defineModel<boolean>('open')

const { teams, activeTeam, setActiveTeam } = useSession()
const { currentUser } = useAuth()

const query = ref('')
watch(open, () => {
	query.value = ''
})

// Search earns its space only once the list outgrows a glance.
const searchable = computed(() => teams.value.length > 6)
const visible = computed(() => {
	const q = query.value.trim().toLowerCase()
	if (!q) return teams.value
	return teams.value.filter((team) => team.label.toLowerCase().includes(q))
})

const standing = (team: Team) =>
	team.owner === currentUser.value ? 'Owner' : 'Member'

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
	<Dialog v-model="open" title="Switch team" size="sm">
		<div class="space-y-3">
			<TextInput
				v-if="searchable"
				v-model="query"
				size="md"
				placeholder="Search teams"
				autofocus
			>
				<template #prefix>
					<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
				</template>
			</TextInput>

			<!-- Teams sit tight together; "Create team" gets the outer gap so it reads
			     as a separate offer rather than one more team you belong to. -->
			<div class="space-y-3">
				<!-- Negative margin + matching padding so the scrollbar rides the modal
				     edge instead of floating inside the content column. The create row
				     sits outside the scroller so it stays reachable at any length. -->
				<div
					class="-mr-4 max-h-80 space-y-1 overflow-y-auto pr-4 sm:-mr-6 sm:pr-6"
				>
					<button
						v-for="team in visible"
						:key="team.name"
						type="button"
						class="flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors duration-150 ease-in-out"
						:class="
							team.name === activeTeam
								? 'border-outline-gray-3'
								: 'border-transparent hover:bg-surface-gray-2'
						"
						@click="selectTeam(team)"
					>
						<Avatar
							:image="team.logo ?? undefined"
							:label="team.label"
							size="xl"
							shape="square"
						/>

						<div class="min-w-0 flex-1">
							<div class="truncate text-base-medium text-ink-gray-8">
								{{ team.label }}
							</div>
							<div class="text-p-sm text-ink-gray-5">{{ standing(team) }}</div>
						</div>

						<span
							v-if="team.name === activeTeam"
							class="lucide-check size-4 shrink-0 text-ink-gray-7"
							aria-hidden="true"
						/>
					</button>

					<p
						v-if="!visible.length"
						class="px-3 py-8 text-center text-p-sm text-ink-gray-5"
					>
						No team matches “{{ query.trim() }}”
					</p>
				</div>

				<button
					type="button"
					class="flex w-full items-center gap-3 rounded-lg border border-transparent px-3 py-2.5 text-left transition-colors duration-150 ease-in-out hover:bg-surface-gray-2"
					@click="createTeam"
				>
					<span
						class="grid size-8 shrink-0 place-items-center rounded-md bg-surface-gray-2"
					>
						<span class="lucide-plus size-4 text-ink-gray-6" aria-hidden="true" />
					</span>
					<div class="min-w-0 flex-1">
						<div class="text-base-medium text-ink-gray-8">Create team</div>
						<div class="text-p-sm text-ink-gray-5">
							Separate servers, members and billing
						</div>
					</div>
				</button>
			</div>
		</div>
	</Dialog>

	<CreateTeamDialog v-model:open="createTeamOpen" />
</template>
