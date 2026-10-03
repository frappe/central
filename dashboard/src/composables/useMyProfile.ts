import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'

// The signed-in user's own profile (display name + photo) — one shared read,
// so the sidebar footer and the profile dialog repaint together after an edit.
interface MyProfile {
	user: string
	full_name: string
	user_image: string | null
}

const profileCall = useCall<MyProfile>({
	url: method(API.myProfile),
	immediate: true,
})

const photoCall = useCall<
	{ user_image: string | null },
	{ file_url: string | null }
>({
	url: method(API.setProfilePhoto),
	method: 'POST',
	immediate: false,
})

/** Set the photo to an uploaded image's URL, or clear it with null. */
async function setPhoto(fileUrl: string | null): Promise<void> {
	await photoCall.submit({ file_url: fileUrl })
	if (photoCall.error) throw photoCall.error
	await profileCall.reload()
}

export function useMyProfile() {
	return {
		profile: computed(() => profileCall.data ?? null),
		loading: computed(() => profileCall.loading),
		savingPhoto: computed(() => photoCall.loading),
		reload: () => profileCall.reload(),
		setPhoto,
	}
}
