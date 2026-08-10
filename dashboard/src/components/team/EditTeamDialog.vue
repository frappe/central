<script setup lang="ts">
import { Avatar, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'

// Edit the team from its header — rename (team:edit) and the danger-zone
// delete (team:delete) — replacing the old full-page Team settings.
// Ownership transfer is NOT here: it lives on the member's ⋯ menu in the
// roster, where the new owner is picked in context. The avatar is the
// team's initial, so it follows the name; image upload waits on a backend
// avatar field.
const open = defineModel<boolean>({ default: false })
const router = useRouter()
const { activeTeam, activeTeamLabel } = useSession()
const { saving, rename, deleteTeam } = useTeamSettings()
const { canEditTeam, canDeleteTeam } = useCapabilities()

const name = ref(activeTeamLabel.value)
watch([open, activeTeam], () => {
	if (open.value) name.value = activeTeamLabel.value
})
const changed = computed(
	() => !!name.value.trim() && name.value.trim() !== activeTeamLabel.value,
)

async function onSave(): Promise<void> {
	if (!changed.value) return
	if (await rename(name.value.trim())) open.value = false
}

// — Danger zone.
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
		open.value = false
		router.push('/servers')
	}
}
</script>

<template>
	<Dialog v-model:open="open" title="Edit team">
		<template #default>
			<div class="space-y-4">
				<!-- Identity row: the avatar sits inline with the name it letters,
				     re-lettering live as the name is typed. -->
				<div class="flex items-end gap-3">
					<Avatar
						:label="name.trim() || activeTeamLabel"
						size="2xl"
						shape="square"
						class="shrink-0"
					/>
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
					Renaming requires the Admin or Owner role.
				</p>

				<!-- Danger zone: title + subtext row, the real friction lives in the
				     confirm step. -->
				<div v-if="canDeleteTeam" class="border-t border-outline-gray-2 pt-4">
					<div class="flex items-center justify-between gap-3">
						<div class="min-w-0">
							<p class="text-base font-medium text-ink-gray-9">Delete team</p>
							<p class="mt-0.5 text-p-sm text-ink-gray-5">
								Permanently removes the team and everyone's access. Servers and
								sites must be removed first.
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
				</div>
			</div>
		</template>
	</Dialog>

	<Dialog
		v-model="confirmDelete"
		:title="deleteOptions.title"
		:message="deleteOptions.message"
		:actions="deleteOptions.actions"
	/>
</template>
