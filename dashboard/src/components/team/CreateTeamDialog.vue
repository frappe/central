<script setup lang="ts">
import { Avatar, Dialog, TextInput } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useCreateTeam } from '@/composables/useCreateTeam'

// Create a new team from the switcher. The caller becomes its Owner; on success
// the app switches to the new team (handled in useTeamSettings). Settings has
// its own inline version of this — both share useCreateTeam.
const open = defineModel<boolean>('open', { default: false })

const { teamName, name, duplicate, canSubmit, saving, submit, reset } =
	useCreateTeam()

watch(open, (isOpen) => {
	if (isOpen) reset()
})

const onSubmit = async () => {
	if (await submit()) open.value = false
}

const actions = computed(() => [
	{
		label: 'Create team',
		variant: 'solid' as const,
		loading: saving.value,
		disabled: !canSubmit.value,
		onClick: onSubmit,
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
					id="team-name"
					v-model="teamName"
					class="min-w-0 flex-1"
					size="md"
					placeholder="e.g. Acme Production"
					autocomplete="off"
					autofocus
					@keyup.enter="onSubmit"
				/>
			</div>
			<p
				class="mt-1.5 text-p-sm"
				:class="duplicate ? 'text-ink-red-6' : 'text-ink-gray-5'"
			>
				{{ duplicate
						? `You already have a team called “${name}”`
						: "You'll be the owner of this team" }}
			</p>
		</div>
	</Dialog>
</template>
