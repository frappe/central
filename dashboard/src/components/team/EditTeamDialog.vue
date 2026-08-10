<script setup lang="ts">
import { Avatar, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { useTeamSettings } from '@/composables/useTeamSettings'
import { errorToast, successToast } from '@/lib/toast'

// Edit the team from its header — logo + rename (team:edit) and the
// danger-zone delete (team:delete) — replacing the old full-page Team
// settings. Ownership transfer is NOT here: it lives on the member's ⋯ menu
// in the roster, where the new owner is picked in context.
const open = defineModel<boolean>({ default: false })
const router = useRouter()
const session = useSession()
const { activeTeam, activeTeamLabel, activeTeamLogo } = session
const { saving, rename, deleteTeam } = useTeamSettings()
const { canEditTeam, canDeleteTeam } = useCapabilities()

const name = ref(activeTeamLabel.value)
watch([open, activeTeam], () => {
	if (open.value) name.value = activeTeamLabel.value
	// Reopening should always start folded — Advanced is opt-in every time.
	else advancedOpen.value = false
})
const changed = computed(
	() => !!name.value.trim() && name.value.trim() !== activeTeamLabel.value,
)

async function onSave(): Promise<void> {
	if (!changed.value) return
	if (await rename(name.value.trim())) open.value = false
}

// — Logo. Uploads as multipart (useCall is JSON-only), then re-pulls the
// session so every Avatar reading the team list repaints at once.
const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)

async function submitLogo(file: File | null): Promise<void> {
	uploading.value = true
	try {
		const body = new FormData()
		body.append('team', activeTeam.value!)
		if (file) body.append('file', file)
		const res = await fetch(method(API.setTeamLogo), {
			method: 'POST',
			headers: { 'X-Frappe-CSRF-Token': window.csrf_token ?? '' },
			body,
		})
		if (!res.ok) {
			const payload = await res.json().catch(() => null)
			throw new Error(
				payload?.errors?.[0]?.message || "Couldn't update the team logo",
			)
		}
		await session.reload()
		successToast(file ? 'Team logo updated' : 'Team logo removed')
	} catch (e) {
		errorToast(e)
	} finally {
		uploading.value = false
	}
}

function onPickLogo(event: Event): void {
	const file = (event.target as HTMLInputElement).files?.[0]
	if (file) submitLogo(file)
	// Reset so picking the same file again still fires @change.
	if (fileInput.value) fileInput.value.value = ''
}

// — Danger zone, behind an Advanced fold.
const advancedOpen = ref(false)
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
			<div class="space-y-5">
				<!-- Logo row with the format hint underneath, no label — the avatar
				     speaks for itself. -->
				<div class="space-y-1.5">
					<div class="flex items-center gap-3">
						<Avatar
							:image="activeTeamLogo ?? undefined"
							:label="name.trim() || activeTeamLabel"
							size="2xl"
							shape="square"
							class="shrink-0"
						/>
						<div v-if="canEditTeam" class="flex items-center gap-2">
							<Button
								:label="activeTeamLogo ? 'Change logo' : 'Upload logo'"
								:loading="uploading"
								@click="fileInput?.click()"
							/>
							<Button
								v-if="activeTeamLogo"
								variant="ghost"
								label="Remove"
								:disabled="uploading"
								@click="submitLogo(null)"
							/>
						</div>
						<input
							ref="fileInput"
							type="file"
							accept="image/png,image/jpeg,image/webp,image/gif"
							class="hidden"
							@change="onPickLogo"
						/>
					</div>
					<p v-if="canEditTeam" class="text-p-sm text-ink-gray-5">
						PNG, JPG, WebP or GIF, up to 2 MB.
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

				<!-- Advanced, folded: deleting a team is rare and destructive, so it
				     stays out of the way until asked for. The real friction lives in
				     the confirm step. -->
				<section v-if="canDeleteTeam">
					<button
						class="-mx-2 flex items-center gap-1.5 rounded-md px-2 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-4"
						:aria-expanded="advancedOpen"
						@click="advancedOpen = !advancedOpen"
					>
						<span
							class="lucide-chevron-right size-3.5 shrink-0 text-ink-gray-5 transition-transform duration-150 ease-out"
							:class="advancedOpen ? 'rotate-90' : ''"
						/>
						<span class="text-base text-ink-gray-6">Advanced</span>
					</button>

					<!-- Button on the title line, not vertically centered — otherwise
					     the wrapping subtext runs underneath it. -->
					<div v-if="advancedOpen" class="mt-3 flex items-start gap-4">
						<div class="min-w-0 flex-1">
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
				</section>
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
