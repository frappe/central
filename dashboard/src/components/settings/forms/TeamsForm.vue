<script setup lang="ts">
import { Avatar, Button, TextInput } from 'frappe-ui'
import { nextTick, ref } from 'vue'
import TeamList from '@/components/team/TeamList.vue'
import { useCreateTeam } from '@/composables/useCreateTeam'
import { closeSettings } from '@/composables/useSettings'

// Your teams, with the active one checked. Picking a row offers to switch and
// switching re-points the console — settings stays open, and the team-scoped
// tabs (Team settings, Notifications) follow the team you moved to rather than
// going stale.
//
// Creating one happens right here rather than in a dialog on top of a dialog:
// a name, an optional logo, and you land in the new team with settings closed.
const { teamName, name, duplicate, canSubmit, saving, submit, reset } =
	useCreateTeam()

const creating = ref(false)
const createRow = ref<HTMLElement | null>(null)

// Revealing the field should put the cursor in it. `autofocus` won't do: the
// browser only honours it for content present when the dialog opens, not for a
// field revealed later.
function startCreating(): void {
	creating.value = true
	nextTick(() => createRow.value?.querySelector('input')?.focus())
}

function cancelCreating(): void {
	creating.value = false
	reset()
}

// Creating a team switches you into it (useTeamSettings), so there's nothing
// left to do here — close settings and let the console land in the new team.
async function onSubmit(): Promise<void> {
	if (!(await submit())) return
	creating.value = false
	closeSettings()
}
</script>

<template>
	<div>
		<TeamList />

		<!-- Subtle, on its own line under the list: creating a team is a real
		     offer but not what most visits here are for. -->
		<Button
			v-if="!creating"
			class="mt-3"
			variant="subtle"
			icon-left="lucide-plus"
			label="Create team"
			@click="startCreating"
		/>

		<div v-else ref="createRow" class="mt-3">
			<label for="new-team-name" class="block text-xs text-ink-gray-5">
				Team name
			</label>
			<!-- The mark is a control, not a preview: click it to pick a logo.
			     Until you do, it shows the initials the team would wear in the
			     list above. -->
			<div class="mt-1.5 flex items-center gap-2">
				<button
					type="button"
					class="relative size-8 shrink-0 rounded-md"
					aria-label="Adding a team logo lands in a follow-up"
					disabled
				>
					<Avatar v-if="name" :label="name" size="xl" shape="square" />
					<span
						v-else
						class="grid size-8 place-items-center rounded-md bg-surface-gray-2"
					>
						<span
							class="lucide-users size-4 text-ink-gray-4"
							aria-hidden="true"
						/>
					</span>
				</button>
				<TextInput
					id="new-team-name"
					v-model="teamName"
					class="min-w-0 flex-1"
					size="md"
					placeholder="e.g. Acme Production"
					autocomplete="off"
					@keyup.enter="onSubmit"
					@keyup.esc="cancelCreating"
				/>
			</div>
			<p
				class="mt-1.5 text-p-sm"
				:class="duplicate ? 'text-ink-red-6' : 'text-ink-gray-5'"
			>
				{{ duplicate
						? `You already have a team called “${name}”`
						: "You'll be the owner, and we'll switch you to it" }}
			</p>

			<div class="mt-3 flex items-center gap-2">
				<Button
					variant="solid"
					label="Create team"
					:loading="saving"
					:disabled="!canSubmit"
					@click="onSubmit"
				/>
				<Button variant="ghost" label="Cancel" @click="cancelCreating" />
			</div>
		</div>
	</div>
</template>
