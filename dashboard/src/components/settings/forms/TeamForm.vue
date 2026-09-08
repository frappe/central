<script setup lang="ts">
import { Avatar, Button, Dialog, FormControl, SettingsRow } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { settingsOpen } from '@/composables/useSettings'
import { useTeamSettings } from '@/composables/useTeamSettings'

const router = useRouter()
const { activeTeamLabel, activeTeamLogo } = useSession()
const { saving, rename, deleteTeam } = useTeamSettings()

const { canEditTeam, canDeleteTeam } = useCapabilities()

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
	<div class="mt-6">
		<div class="space-y-6">
			<div v-if="canEditTeam">
				<p class="block text-base text-ink-gray-5">Logo</p>
				<div class="mt-1.5 flex items-center gap-3">
					<Avatar
						:image="activeTeamLogo ?? undefined"
						:label="name.trim() || activeTeamLabel"
						size="3xl"
						shape="square"
						class="size-12 shrink-0"
					/>
					<div class="flex flex-col items-start gap-1">
						<Button
							size="xs"
							variant="subtle"
							icon-left="lucide-upload"
							:label="activeTeamLogo ? 'Change' : 'Upload'"
						/>
						<Button
							v-if="activeTeamLogo"
							size="xs"
							variant="ghost"
							theme="red"
							icon-left="lucide-trash-2"
							label="Delete"
						/>
					</div>
				</div>
			</div>

			<div class="flex items-end gap-2">
				<FormControl
					v-model="name"
					label="Team name"
					class="flex-1"
					:disabled="!canEditTeam"
					@keydown.enter="onSave"
				/>
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

		<div v-if="canDeleteTeam" class="mt-8 border-t border-outline-gray-1">
			<SettingsRow
				title="Delete team"
				description="Permanently delete this team. Remove its servers and sites first."
			>
				<Button
					theme="red"
					variant="subtle"
					label="Delete"
					@click="confirmDelete = true"
				/>
			</SettingsRow>
		</div>

		<Dialog
			v-model="confirmDelete"
			:title="deleteOptions.title"
			:message="deleteOptions.message"
			:actions="deleteOptions.actions"
		/>
	</div>
</template>
