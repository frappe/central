<script setup lang="ts">
import { Avatar, Button, FormControl, useCall } from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useMyProfile } from '@/composables/useMyProfile'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { errorToast, successToast } from '@/lib/toast'

// The signed-in user's own profile — photo, display name, password. Chrome-free
// on purpose: the settings dialog wraps it in a panel, mobile renders it as a
// page, and neither layout leaks in here.
const { profile, reload: reloadProfile } = useMyProfile()
// The roster renders member photos, so it repaints after a change too.
const { reload: reloadMembers } = useTeamMembers()

const name = ref(profile.value?.full_name ?? '')
watch(profile, (p) => {
	name.value = p?.full_name ?? ''
})
const changed = computed(
	() =>
		!!name.value.trim() &&
		name.value.trim() !== (profile.value?.full_name ?? ''),
)

const saveCall = useCall<{ full_name: string }, { full_name: string }>({
	url: method(API.updateProfile),
	method: 'POST',
	immediate: false,
})
const saving = ref(false)

async function onSave(): Promise<void> {
	if (!changed.value) return
	saving.value = true
	try {
		await saveCall.submit({ full_name: name.value.trim() })
		if (saveCall.error) throw saveCall.error
		await Promise.all([reloadProfile(), reloadMembers()])
		successToast('Name updated')
	} catch (e) {
		errorToast(e)
	} finally {
		saving.value = false
	}
}

// — Photo. The row is here but inert: the upload endpoint is held back for a
// follow-up PR, so the control shows what's coming without pretending to work.

// — Password. The fields stay out of the way until asked for: most visits here
// are about the photo or name.
const editingPassword = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const changingPassword = ref(false)

// Revealing the fields should put the cursor where the work starts.
const currentPasswordRef = ref<{ $el?: HTMLElement } | null>(null)
watch(editingPassword, (editing) => {
	if (!editing) return
	nextTick(() => currentPasswordRef.value?.$el?.querySelector('input')?.focus())
})

const canChangePassword = computed(
	() => !!oldPassword.value && newPassword.value.length >= 8,
)

const passwordCall = useCall<
	{ changed: boolean },
	{ old_password: string; new_password: string }
>({
	url: method(API.changePassword),
	method: 'POST',
	immediate: false,
})

async function onChangePassword(): Promise<void> {
	if (!canChangePassword.value) return
	changingPassword.value = true
	try {
		await passwordCall.submit({
			old_password: oldPassword.value,
			new_password: newPassword.value,
		})
		if (passwordCall.error) throw passwordCall.error
		resetPassword()
		successToast('Password changed. Your other sessions were signed out')
	} catch (e) {
		errorToast(e)
	} finally {
		changingPassword.value = false
	}
}

function resetPassword(): void {
	editingPassword.value = false
	oldPassword.value = ''
	newPassword.value = ''
}
</script>

<template>
	<div class="space-y-6">
		<!-- Photo row, no label — the avatar speaks for itself. The control is
		     disabled until the upload endpoint lands. -->
		<div class="space-y-1.5">
			<div class="flex items-center gap-3">
				<Avatar
					:image="profile?.user_image ?? undefined"
					:label="name.trim() || profile?.full_name || profile?.user || ''"
					size="2xl"
					class="shrink-0"
				/>
				<Button
					:label="profile?.user_image ? 'Change photo' : 'Upload photo'"
					disabled
				/>
			</div>
			<p class="text-p-sm text-ink-gray-5">
				Photo uploads land in a follow-up.
			</p>
		</div>

		<div class="flex items-end gap-2">
			<FormControl
				v-model="name"
				label="Full name"
				class="flex-1"
				@keydown.enter="onSave"
			/>
			<!-- Save only exists once there's something to save. -->
			<Button
				v-if="changed"
				variant="solid"
				label="Save"
				:loading="saving"
				@click="onSave"
			/>
		</div>

		<!-- Identity, not a setting — disabled (not readonly) so it can't be
		     focused or clicked into at all. -->
		<FormControl :model-value="profile?.user ?? ''" label="Email" disabled />

		<!-- One button until you mean it; the fields appear in place. The button
		     and field labels name themselves — no section label. -->
		<div>
			<Button
				v-if="!editingPassword"
				label="Change password"
				@click="editingPassword = true"
			/>
			<div v-else class="space-y-3">
				<FormControl
					ref="currentPasswordRef"
					v-model="oldPassword"
					type="password"
					label="Current password"
					autocomplete="current-password"
				/>
				<FormControl
					v-model="newPassword"
					type="password"
					label="New password"
					autocomplete="new-password"
					description="At least 8 characters. Your other sessions will be signed out."
					@keydown.enter="onChangePassword"
				/>
				<!-- Distinct submit label (the trigger already said "Change
				     password") and a ghost Cancel, so the primary reads as primary
				     even while disabled. -->
				<div class="flex items-center gap-2">
					<Button
						variant="solid"
						label="Update password"
						:loading="changingPassword"
						:disabled="!canChangePassword"
						@click="onChangePassword"
					/>
					<Button variant="ghost" label="Cancel" @click="resetPassword" />
				</div>
			</div>
		</div>
	</div>
</template>
