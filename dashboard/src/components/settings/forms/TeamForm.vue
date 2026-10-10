<script setup lang="ts">
import { Alert, Button, Dialog, SettingsRow, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import ImageUpload from '@/components/common/ImageUpload.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { settingsOpen } from '@/composables/useSettings'
import { useTeamSettings } from '@/composables/useTeamSettings'

const router = useRouter()
const { activeTeam, activeTeamLabel, activeTeamLogo } = useSession()
const { saving, error, clearError, rename, setLogo, deleteTeam } =
	useTeamSettings()

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
watch(name, clearError)

const confirmDelete = ref(false)
const deleteOptions = computed(() => ({
	title: 'Delete team',
	message: `Permanently delete “${activeTeamLabel.value}”? This can't be undone.`,
	actions: [
		{
			label: 'Delete team',
			variant: 'solid' as const,
			theme: 'red' as const,
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
			<Alert v-if="error && !confirmDelete" theme="red" :title="error" />
			<ImageUpload
				v-if="canEditTeam && activeTeam"
				label="Logo"
				:name="name.trim() || activeTeamLabel"
				:image="activeTeamLogo"
				:attach-to="{
					doctype: 'Team',
					docname: activeTeam,
					fieldname: 'team_logo',
				}"
				shape="square"
				:busy="saving"
				@change="setLogo"
			/>

			<div class="flex items-end gap-2">
				<TextInput
					v-model="name"
					v-focus="canEditTeam"
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
				<Button theme="red" label="Delete" @click="confirmDelete = true" />
			</SettingsRow>
		</div>

		<Dialog
			v-model="confirmDelete"
			:title="deleteOptions.title"
			:message="deleteOptions.message"
			:actions="deleteOptions.actions"
		>
			<Alert v-if="error" theme="red" :title="error" />
		</Dialog>
	</div>
</template>
