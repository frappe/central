<script setup lang="ts">
import { Avatar, Dialog, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'

// Create a new team. The caller becomes its Owner; on success the app switches to
// the new team (handled in useTeamSettings).
const open = defineModel<boolean>('open', { default: false })

const { saving, createTeam } = useTeamSettings()
const { teams } = useSession()

const teamName = ref('')
watch(open, (isOpen) => {
	if (isOpen) teamName.value = ''
})

const name = computed(() => teamName.value.trim())

// Duplicate names are legal, but a switcher of identical rows is unusable — so
// say so before the team exists rather than after.
const duplicate = computed(() =>
	teams.value.some((team) => team.label.toLowerCase() === name.value.toLowerCase()),
)
const canSubmit = computed(() => name.value.length > 0 && !duplicate.value)

const submit = async () => {
	if (!canSubmit.value) return
	if (await createTeam(name.value)) open.value = false
}

const actions = computed(() => [
	{
		label: 'Create team',
		variant: 'solid' as const,
		loading: saving.value,
		disabled: !canSubmit.value,
		onClick: submit,
	},
])
</script>

<template>
	<Dialog v-model="open" title="Create a team" size="sm" :actions="actions">
		<!-- Label and helper span the row so everything shares one left edge; the
		     avatar matches the input's height, so the two read as one control. It
		     previews the mark the team will wear in the switcher — the name is a
		     choice you can see, not just a string you type. -->
		<div>
			<label for="team-name" class="block text-xs text-ink-gray-5">
				Team name
			</label>
			<div class="mt-1.5 flex items-center gap-2">
				<Avatar
					v-if="name"
					:label="name"
					size="xl"
					shape="square"
					class="shrink-0"
				/>
				<div
					v-else
					class="grid size-8 shrink-0 place-items-center rounded-md bg-surface-gray-2"
				>
					<span class="lucide-users size-4 text-ink-gray-4" aria-hidden="true" />
				</div>
				<TextInput
					id="team-name"
					v-model="teamName"
					class="min-w-0 flex-1"
					size="md"
					placeholder="e.g. Acme Production"
					autocomplete="off"
					autofocus
					@keyup.enter="submit"
				/>
			</div>
			<p
				class="mt-1.5 text-p-sm"
				:class="duplicate ? 'text-ink-red-6' : 'text-ink-gray-5'"
			>
				{{
					duplicate
						? `You already have a team called “${name}”`
						: "You'll be the owner of this team"
				}}
			</p>
		</div>
	</Dialog>
</template>
