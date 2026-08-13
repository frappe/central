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

export function useMyProfile() {
	return {
		profile: computed(() => profileCall.data ?? null),
		loading: computed(() => profileCall.loading),
		reload: () => profileCall.reload(),
	}
}
