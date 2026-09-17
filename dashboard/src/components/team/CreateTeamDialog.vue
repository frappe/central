<script setup lang="ts">
import { Avatar, Dialog, TextInput } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useCreateTeam } from '@/composables/useCreateTeam'

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
		<div>
			<label for="team-name" class="block text-xs text-ink-gray-5">
				Team name
			</label>
			<div class="mt-1.5 flex items-center gap-2">
				<button
					type="button"
					class="relative size-8 shrink-0 rounded-5"
					aria-label="Adding a team logo lands in a follow-up"
					disabled
				>
					<Avatar v-if="name" :label="name" size="xl" shape="square" />
					<span
						v-else
						class="grid size-8 place-items-center rounded-5 bg-surface-gray-2"
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
				:class="duplicate ? 'text-ink-red-5' : 'text-ink-gray-5'"
			>
				{{ duplicate
						? `You already have a team called “${name}”`
						: "You'll be the owner of this team" }}
			</p>
		</div>
	</Dialog>
</template>
