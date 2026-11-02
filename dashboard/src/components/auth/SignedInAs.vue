<script setup lang="ts">
import { Button, ErrorMessage } from 'frappe-ui'
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from '@/composables/useAuth'
import { useSession } from '@/composables/useSession'
import { queryString } from '@/lib/auth'

const route = useRoute()
const { currentUser, logout } = useAuth()
const { activeTeamLabel } = useSession()
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
	<div class="mt-8 border-t border-outline-gray-2 pt-4">
		<div class="flex items-center justify-between gap-2">
			<div class="min-w-0 text-p-sm text-ink-gray-5">
				<p class="truncate">
					Signed in as
					<span class="text-ink-gray-8">{{ currentUser }}</span>
				</p>
				<p class="truncate">
					Team <span class="text-ink-gray-8">{{ activeTeamLabel }}</span>
				</p>
			</div>
			<Button
				variant="ghost"
				size="sm"
				label="Sign out"
				:loading="isSigningOut"
				@click="signOut"
			/>
		</div>
		<ErrorMessage v-if="error" class="mt-2" :message="error" />
	</div>
</template>
