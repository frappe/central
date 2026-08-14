<script setup lang="ts">
import {
	Avatar,
	Button,
	vOnOutsideClick,
	TextInput,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import { forgetSettingsOrigin } from '@/composables/useSettings'
import type { Team } from '@/types/api'

// Every team you belong to, one row each: name, then your standing in it, so
// the list keeps one rhythm and the check alone says where you are.
//
// Switching takes two steps on purpose. It re-points the whole console — every
// page, list and bill behind this panel — so a stray click on the wrong row
// shouldn't do it. Picking a row selects it and offers "Switch team"; nothing
// moves until that's pressed.
const emit = defineEmits<{ switched: [team: Team] }>()

const { teams, activeTeam, setActiveTeam } = useSession()
const { currentUser } = useAuth()

const query = ref('')
const selected = ref<string | null>(null)

// Search earns its space only once the list outgrows a glance.
const searchable = computed(() => teams.value.length > 6)
const visible = computed(() => {
	const q = query.value.trim().toLowerCase()
	if (!q) return teams.value
	return teams.value.filter((team) => team.label.toLowerCase().includes(q))
})

// A selection that scrolls out of the filtered list would leave its button
// stranded off-screen, so filtering clears it.
watch(query, () => {
	selected.value = null
})

const standing = (team: Team) =>
	team.owner === currentUser.value ? 'Owner' : 'Member'

function selectTeam(team: Team): void {
	if (team.name === activeTeam.value) return
	selected.value = selected.value === team.name ? null : team.name
}

function switchTo(team: Team): void {
	setActiveTeam(team.name)
	// This list lives inside settings, so closing them would otherwise land on
	// whatever page the old team was on — a server, an invoice — which the new
	// team may not be able to read at all.
	forgetSettingsOrigin()
	selected.value = null
	emit('switched', team)
}
</script>

<template>
	<div class="space-y-3">
		<TextInput
			v-if="searchable"
			v-model="query"
			size="md"
			placeholder="Search teams"
		>
			<template #prefix>
				<span class="lucide-search size-4 text-ink-gray-5" aria-hidden="true" />
			</template>
		</TextInput>

		<!-- Negative margin + matching padding so the scrollbar rides the outer
		     edge instead of floating inside the content column.

		     A selection is an offer, not a mode: clicking away withdraws it the
		     same way clicking the row again does. Without this the "Switch team"
		     button sat there indefinitely, since nothing outside the list cleared
		     it. -->
		<div
			v-on-outside-click="() => (selected = null)"
			class="-mr-4 max-h-80 space-y-1 overflow-y-auto pr-4 sm:-mr-6 sm:pr-6"
		>
			<!-- The row is a div holding a button, not a button holding a button:
			     the name area selects, the action beside it switches. -->
			<div
				v-for="team in visible"
				:key="team.name"
				class="flex items-center gap-3 rounded-6 border px-3 py-2.5 transition-colors duration-150 ease-in-out"
				:class="
					team.name === activeTeam || team.name === selected
						? 'border-outline-gray-3'
						: 'border-transparent hover:bg-surface-gray-2'
				"
			>
				<button
					type="button"
					class="flex min-w-0 flex-1 items-center gap-3 text-left focus-visible:outline-none"
					:aria-pressed="team.name === selected"
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
				</button>

				<span
					v-if="team.name === activeTeam"
					class="lucide-check size-4 shrink-0 text-ink-gray-7"
					aria-hidden="true"
				/>
				<!-- `label` stays the full "Switch to <team>" for screen readers —
				     the row it belongs to isn't announced with it. The visible text
				     is just the verb; the row already names the team. -->
				<Button
					v-else-if="team.name === selected"
					variant="solid"
					icon-left="lucide-repeat"
					:label="`Switch to ${team.label}`"
					class="shrink-0"
					@click="switchTo(team)"
				>
					Switch
				</Button>
			</div>

			<p
				v-if="!visible.length"
				class="px-3 py-8 text-center text-p-sm text-ink-gray-5"
			>
				No team matches “{{ query.trim() }}”
			</p>
		</div>
	</div>
</template>
