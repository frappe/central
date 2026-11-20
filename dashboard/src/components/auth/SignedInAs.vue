<script setup lang="ts">
import { ErrorMessage } from 'frappe-ui'
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import { queryString } from '@/lib/auth'

const route = useRoute()
const { currentUser, logout } = useAuth()
const { teams, activeTeamLabel } = useSession()
const isSigningOut = ref(false)
const error = ref('')

// A product link opened in someone else's session goes back to that product's signup.
async function signOut() {
	isSigningOut.value = true
	error.value = ''
	try {
		await logout()
		const product = queryString(route.query.product)
		window.location.replace(
			product
				? `/dashboard/signup?${new URLSearchParams({ product })}`
				: '/dashboard/login',
		)
	} catch {
		error.value = "We couldn't sign you out. Try again."
		isSigningOut.value = false
	}
}
</script>

<template>
	<!-- Only a user with several teams can create the site on the wrong one. -->
	<div v-if="teams.length > 1">
		<p class="text-p-sm text-ink-gray-5">
			Creating in
			<span class="text-ink-gray-7">{{ activeTeamLabel }}</span>
			as
			<span
				class="inline-block max-w-full truncate align-bottom text-ink-gray-7"
				:title="currentUser ?? undefined"
				>{{ currentUser }}</span
			>.
			<button
				type="button"
				class="text-p-sm-medium text-ink-gray-8 hover:underline focus-visible:underline disabled:opacity-60"
				:disabled="isSigningOut"
				@click="signOut"
			>
				{{ isSigningOut ? 'Signing out…' : 'Not you?' }}
			</button>
		</p>
		<ErrorMessage v-if="error" class="mt-2" :message="error" />
	</div>
</template>
