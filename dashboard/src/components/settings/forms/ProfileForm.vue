<script setup lang="ts">
import { Alert, Button, TextInput, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import ImageUpload from '@/components/common/ImageUpload.vue'
import { useMyProfile } from '@/composables/useMyProfile'
import { useTeamMembers } from '@/composables/useTeamMembers'
import { getErrorMessage, successToast } from '@/lib/feedback'

// The signed-in user's own profile: photo and display name. Chrome-free
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
				v-focus
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
	</div>
</template>
