<script setup lang="ts">
import { useSession } from '@/composables/useSession'
import { useAppMenu } from '@/composables/useAppMenu'

const { activeTeamLabel } = useSession()
const {
	currentUser,
	themeOptions,
	currentTheme,
	setTheme,
	changeTeamOpen,
	logoutAndRedirect,
} = useAppMenu()
</script>

<template>
	<div class="flex h-full flex-col">
		<div class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
			<div
				class="mx-auto max-w-2xl divide-y divide-outline-gray-1 rounded-lg ring-1 ring-outline-gray-1"
			>
				<button
					class="flex w-full items-center justify-between gap-4 px-4 py-3 text-left hover:bg-surface-gray-2"
					@click="changeTeamOpen = true"
				>
					<span class="text-sm text-ink-gray-8">Team</span>
					<span class="flex items-center gap-1 text-p-sm text-ink-gray-5">
						{{ activeTeamLabel }}
						<span class="lucide-chevron-right size-4" />
					</span>
				</button>

				<div class="flex items-center justify-between gap-4 px-4 py-3">
					<span class="text-sm text-ink-gray-8">Theme</span>
					<div class="flex gap-1">
						<button
							v-for="theme in themeOptions"
							:key="theme.value"
							class="rounded px-2 py-1 text-p-sm"
							:class="
								currentTheme === theme.value
									? 'bg-surface-gray-3 text-ink-gray-9'
									: 'text-ink-gray-5'
							"
							@click="setTheme(theme.value as 'light' | 'dark' | 'system')"
						>
							{{ theme.label }}
						</button>
					</div>
				</div>

				<div class="flex items-center justify-between gap-4 px-4 py-3">
					<span class="text-sm text-ink-gray-8">Account</span>
					<span class="truncate text-p-sm text-ink-gray-5">{{ currentUser }}</span>
				</div>

				<button
					class="flex w-full items-center justify-between px-4 py-3 text-left text-sm text-ink-red-5 hover:bg-surface-gray-2"
					@click="logoutAndRedirect"
				>
					Sign out
				</button>
			</div>
		</div>
	</div>
</template>
