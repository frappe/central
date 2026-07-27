<script setup lang="ts">
import { useRouter } from 'vue-router'
import NotificationPreferences from '@/components/notifications/NotificationPreferences.vue'

const router = useRouter()
</script>

<template>
	<div class="flex h-full flex-col">
		<div class="flex items-center justify-between border-b border-outline-gray-1 px-4 py-3 sm:px-6">
			<h1 class="text-lg font-semibold text-ink-gray-9">Notification preferences</h1>
			<button
				class="text-p-sm text-ink-gray-5 hover:text-ink-gray-8"
				@click="router.push({ name: 'Notifications' })"
			>
				Back to notifications
			</button>
		</div>

		<div class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
			<div class="mx-auto max-w-2xl">
				<NotificationPreferences />
			</div>
		</div>
	</div>
</template>
