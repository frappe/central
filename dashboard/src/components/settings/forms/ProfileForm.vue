<script setup lang="ts">
import { Alert, Button, TextInput, useCall } from 'frappe-ui'
import { computed, nextTick, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import ImageUpload from '@/components/common/ImageUpload.vue'
import { useMyProfile } from '@/composables/useMyProfile'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { getErrorMessage, successToast } from '@/lib/feedback'

// The signed-in user's own profile — photo, display name, password. Chrome-free
// on purpose: the settings dialog wraps it in a panel, mobile renders it as a
// page, and neither layout leaks in here.
const { profile, savingPhoto, reload: reloadProfile, setPhoto } = useMyProfile()
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
const nameError = ref('')
watch(name, () => (nameError.value = ''))

async function onSave(): Promise<void> {
	if (!changed.value) return
	saving.value = true
	try {
		await saveCall.submit({ full_name: name.value.trim() })
		if (saveCall.error) throw saveCall.error
		await Promise.all([reloadProfile(), reloadMembers()])
		successToast('Name updated')
	} catch (e) {
		nameError.value = getErrorMessage(e, "Your name couldn't be updated.")
	} finally {
		saving.value = false
	}
}

const photoError = ref('')

async function onPhotoChange(fileUrl: string | null): Promise<void> {
	photoError.value = ''
	try {
		await setPhoto(fileUrl)
		await reloadMembers()
		successToast(fileUrl ? 'Photo updated' : 'Photo removed')
	} catch (e) {
		photoError.value = getErrorMessage(e, "Your photo couldn't be updated.")
	}
}

// — Password. The fields stay out of the way until asked for: most visits here
// are about the photo or name.
const editingPassword = ref(false)
const oldPassword = ref('')
const newPassword = ref('')
const changingPassword = ref(false)
const passwordError = ref('')
watch([oldPassword, newPassword], () => (passwordError.value = ''))

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
		passwordError.value = getErrorMessage(
			e,
			"Your password couldn't be changed.",
		)
	} finally {
		changingPassword.value = false
	}
}

function resetPassword(): void {
	editingPassword.value = false
	oldPassword.value = ''
	newPassword.value = ''
	passwordError.value = ''
}
</script>

<template>
	<div class="mt-6 space-y-6">
		<div v-if="profile">
			<Alert v-if="photoError" class="mb-3" theme="red" :title="photoError" />
			<ImageUpload
				label="Photo"
				:name="name.trim() || profile.full_name || profile.user"
				:image="profile.user_image"
				:attach-to="{
					doctype: 'User',
					docname: profile.user,
					fieldname: 'user_image',
				}"
				:busy="savingPhoto"
				@change="onPhotoChange"
			/>
		</div>

		<Alert v-if="nameError" class="mb-3" theme="red" :title="nameError" />
		<div class="flex items-end gap-2">
			<TextInput
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
		<TextInput :model-value="profile?.user ?? ''" label="Email" disabled />

		<!-- One button until you mean it; the fields appear in place. The button
		     and field labels name themselves — no section label. -->
		<div>
			<Button
				v-if="!editingPassword"
				label="Change password"
				@click="editingPassword = true"
			/>
			<div v-else class="space-y-3">
				<Alert v-if="passwordError" theme="red" :title="passwordError" />
				<TextInput
					ref="currentPasswordRef"
					v-model="oldPassword"
					type="password"
					label="Current password"
					autocomplete="current-password"
				/>
				<TextInput
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
