<script setup lang="ts">
import { Avatar, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { settingsOpen } from '@/composables/useSettings'
import { useTeamSettings } from '@/composables/useTeamSettings'

// The active team's own settings — rename (team:edit) and the delete row
// (team:delete). Ownership transfer is NOT here: it lives on the member's ⋯
// menu in the roster, where the new owner is picked in context.
const router = useRouter()
const { activeTeamLabel, activeTeamLogo } = useSession()
const { saving, rename, deleteTeam } = useTeamSettings()
const { canEditTeam, canDeleteTeam } = useCapabilities()

// Switching teams while this is open re-points the form at the new team.
const name = ref(activeTeamLabel.value)
watch(activeTeamLabel, (label) => {
	name.value = label
})
const changed = computed(
	() => !!name.value.trim() && name.value.trim() !== activeTeamLabel.value,
)

async function onSave(): Promise<void> {
	if (!changed.value) return
	await rename(name.value.trim())
}

// — Logo. The row is here but inert: the upload endpoint is held back for a
// follow-up PR, so the control shows what's coming without pretending to work.

// — Deleting the team. It sits last, under a rule, and the real friction is
// the confirm step.
const confirmDelete = ref(false)
const deleteOptions = computed(() => ({
	title: 'Delete team',
	message: `Permanently delete “${activeTeamLabel.value}”? This can't be undone.`,
	actions: [
		{
			label: 'Delete team',
			variant: 'solid' as const,
			theme: 'red' as const,
			loading: saving.value,
			onClick: onDelete,
		},
	],
}))

async function onDelete(): Promise<void> {
	if (await deleteTeam()) {
		confirmDelete.value = false
		settingsOpen.value = false
		router.push('/servers')
	}
}
</script>

<template>
	<div>
		<div class="space-y-6">
			<!-- Logo row, no label — the avatar speaks for itself. The control is
			     disabled until the upload endpoint lands. -->
			<div class="space-y-1.5">
				<div class="flex items-center gap-3">
					<!-- Square: this is the organisation, not a person. -->
					<Avatar
						:image="activeTeamLogo ?? undefined"
						:label="name.trim() || activeTeamLabel"
						size="2xl"
						shape="square"
						class="shrink-0"
					/>
					<Button
						v-if="canEditTeam"
						:label="activeTeamLogo ? 'Change logo' : 'Upload logo'"
						disabled
					/>
				</div>
				<p v-if="canEditTeam" class="text-p-sm text-ink-gray-5">
					Logo uploads land in a follow-up.
				</p>
			</div>

			<div class="flex items-end gap-2">
				<FormControl
					v-model="name"
					label="Team name"
					class="flex-1"
					:disabled="!canEditTeam"
					@keydown.enter="onSave"
				/>
				<!-- Save only exists once there's something to save — an
				     always-there disabled button is just furniture. -->
				<Button
					v-if="canEditTeam && changed"
					variant="solid"
					label="Save"
					:loading="saving"
					@click="onSave"
				/>
			</div>
			<p v-if="!canEditTeam" class="text-p-sm text-ink-gray-5">
				Editing the team requires the Admin or Owner role.
			</p>
		</div>

		<!-- Deleting is rare and destructive: it goes last, past a rule, on the
		     line with its own explanation. -->
		<div
			v-if="canDeleteTeam"
			class="mt-10 flex items-start gap-4 border-t border-outline-gray-1 pt-6"
		>
			<div class="min-w-0 flex-1">
				<p class="text-base font-medium text-ink-gray-9">Delete team</p>
				<p class="mt-0.5 text-p-sm text-ink-gray-5">
					Permanently removes the team and everyone's access. Servers and sites
					must be removed first.
				</p>
			</div>
			<Button
				theme="red"
				variant="subtle"
				label="Delete"
				class="shrink-0"
				@click="confirmDelete = true"
			/>
		</div>

		<Dialog
			v-model="confirmDelete"
			:title="deleteOptions.title"
			:message="deleteOptions.message"
			:actions="deleteOptions.actions"
		/>
	</div>
</template>
