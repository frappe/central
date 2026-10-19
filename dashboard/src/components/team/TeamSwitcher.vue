<script setup lang="ts">
import { Alert, Avatar, Button, Popover, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import frappeCloudLogo from '@/assets/fc-logo.svg'
import { useMenuKeyboardNavigation } from '@/composables/useMenuKeyboardNavigation'
import { useSession } from '@/composables/useSession'
import { teamSwitcherOpen } from '@/composables/useTeamSwitcher'
import { getErrorMessage } from '@/lib/feedback'
import { getTeamSwitcherRows } from '@/lib/teamSwitcher'
import CreateTeamDialog from './CreateTeamDialog.vue'

interface TeamSwitcherProps {
	collapsed?: boolean
}

defineProps<TeamSwitcherProps>()

const session = useSession()
const { teams, activeTeam, activeTeamLabel, loading, error } = session
const query = ref('')
const switchError = ref('')
const switching = ref(false)
const createTeamOpen = ref(false)
const searchable = computed(() => teams.value.length > 6)
const activeTeamTitle = computed(() =>
	activeTeam.value ? activeTeamLabel.value : 'Select a team',
)
const teamRows = computed(() => getTeamSwitcherRows(teams.value))
const activeTeamIdentity = computed(
	() =>
		teamRows.value.find((team) => team.name === activeTeam.value)?.identity ??
		activeTeamTitle.value,
)
const visibleTeams = computed(() => {
	const search = query.value.trim().toLowerCase()
	return teamRows.value.filter((team) =>
		`${team.label} ${team.detail}`.toLowerCase().includes(search),
	)
})
// A partner's staff see the clients they work for after their own teams.
const teamGroups = computed(() =>
	[
		{ label: '', teams: visibleTeams.value.filter((t) => !t.via_partner) },
		{
			label: 'Clients',
			teams: visibleTeams.value.filter((t) => t.via_partner),
		},
	].filter((group) => group.teams.length),
)

watch(teamSwitcherOpen, () => {
	query.value = ''
	switchError.value = ''
})
watch(searchable, (shown) => {
	if (!shown) query.value = ''
})

function switchTeam(name: string): void {
	if (name === activeTeam.value) return

	switching.value = true
	try {
		session.setActiveTeam(name)
	} catch (error) {
		switchError.value = getErrorMessage(error)
		switching.value = false
	}
}

function createTeam(): void {
	teamSwitcherOpen.value = false
	createTeamOpen.value = true
}

const { onKeydown } = useMenuKeyboardNavigation(() => {
	teamSwitcherOpen.value = false
})
</script>

<template>
	<div
		class="flex h-12 shrink-0 items-center"
		:class="collapsed ? 'px-1' : 'px-2'"
	>
		<Popover v-model:open="teamSwitcherOpen" align="start" match-trigger-width>
			<template #trigger>
				<Button
					variant="ghost"
					size="lg"
					aria-label="Switch team"
					:tooltip="activeTeamIdentity"
					class="team-switcher-button w-full !justify-start !px-1.5 !text-left"
				>
					<template #prefix>
						<img
							:src="frappeCloudLogo"
							alt="Frappe Cloud"
							class="size-6 shrink-0"
						/>
					</template>
					<span v-if="!collapsed" class="flex min-w-0 flex-col gap-0.5">
						<span class="truncate text-sm-medium text-ink-gray-8"
							>Frappe Cloud</span
						>
						<span class="truncate text-sm text-ink-gray-6"
							>{{ activeTeamTitle }}</span
						>
					</span>
					<template v-if="!collapsed" #suffix>
						<span
							class="lucide-chevrons-up-down ml-auto size-4 shrink-0 text-ink-gray-5"
							aria-hidden="true"
						/>
					</template>
				</Button>
			</template>

			<div class="w-64 max-w-full p-1" aria-label="Teams" @keydown="onKeydown">
				<TextInput
					v-if="searchable"
					v-model="query"
					aria-label="Search teams"
					placeholder="Search teams"
					class="mb-1"
				/>
				<Alert
					v-if="switchError || error"
					theme="red"
					:title="switchError || getErrorMessage(error, 'Could not load teams.')"
					class="mb-2"
				/>
				<Button
					v-if="error"
					label="Retry"
					:loading="loading"
					@click="session.reload"
				/>
				<p v-if="loading" class="p-3 text-p-sm text-ink-gray-5" role="status">
					Loading teams…
				</p>
				<p v-if="switching" class="p-2 text-p-sm text-ink-gray-5" role="status">
					Switching team…
				</p>
				<div v-if="!loading && !switching" class="max-h-64 overflow-y-auto">
					<div
						v-for="group in teamGroups"
						:key="group.label"
						role="group"
						:aria-label="group.label || 'Your teams'"
					>
						<p
							v-if="group.label"
							class="px-2 pb-1 pt-2 text-sm text-ink-gray-5"
						>
							{{ group.label }}
						</p>
						<Button
							v-for="team in group.teams"
							:key="team.name"
							variant="ghost"
							size="sm"
							:aria-label="team.identity"
							:tooltip="team.identity"
							:aria-pressed="team.name === activeTeam"
							class="team-switcher-button w-full !justify-start !px-2 focus-visible:bg-surface-gray-3 focus-visible:outline focus-visible:outline-1 focus-visible:-outline-offset-1 focus-visible:outline-outline-gray-3"
							:class="{
								'!h-auto !py-1.5': team.detail,
								'!bg-surface-gray-3': team.name === activeTeam,
							}"
							@click="switchTeam(team.name)"
						>
							<template #prefix>
								<Avatar
									:image="team.logo ?? undefined"
									:label="team.label"
									size="sm"
									shape="square"
								/>
							</template>
							<span class="flex min-w-0 flex-col text-left">
								<span class="truncate">{{ team.label }}</span>
								<span
									v-if="team.detail"
									class="truncate text-sm text-ink-gray-6"
									>{{ team.detail }}</span
								>
							</span>
							<template #suffix>
								<span
									class="ml-auto size-4 shrink-0"
									:class="team.name === activeTeam ? 'lucide-check' : ''"
									aria-hidden="true"
								/>
							</template>
						</Button>
					</div>
					<p
						v-if="!visibleTeams.length && !error"
						class="p-3 text-p-sm text-ink-gray-5"
					>
						{{ query ? 'No matching teams.' : 'You do not belong to a team yet.' }}
					</p>
				</div>
				<div class="mt-1 border-t border-outline-gray-2 pt-1">
					<Button
						variant="ghost"
						icon-left="lucide-plus"
						label="Create team"
						class="w-full !justify-start"
						:disabled="switching"
						@click="createTeam"
					/>
				</div>
			</div>
		</Popover>
	</div>
	<CreateTeamDialog v-model:open="createTeamOpen" />
</template>

<style>
/* Button's label wrapper must yield space to the avatar and trailing icon. */
.team-switcher-button > span.truncate {
	min-width: 0;
	flex: 1;
}
</style>
