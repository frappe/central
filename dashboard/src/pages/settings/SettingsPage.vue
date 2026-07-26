<script setup lang="ts">
import { useSession } from '@/composables/useSession'
import { useAppMenu } from '@/composables/useAppMenu'
import { Button } from 'frappe-ui'

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
	<div class="m-2  divide-y divide-outline-gray-1 rounded border">
		<Button
			variant="ghost"
			class=" w-full !justify-between text-base"
			size="lg"
			@click="changeTeamOpen = true"
		>
			Team
			<template #suffix>
				<span class="flex items-center gap-1 text-p-sm text-ink-gray-5">
					{{ activeTeamLabel }}
					<span class="lucide-chevron-right size-4" />
				</span>
			</template>
		</Button>

		<div class="flex items-center justify-between gap-4 px-4 py-3">
			<span class="text-ink-gray-8">Account</span>
			<span class="truncate text-p-base text-ink-gray-5"
				>{{ currentUser }}</span
			>
		</div>

		<div class="flex items-center gap-4 px-4 py-3">
			<span class="text-base text-ink-gray-8 mr-auto">Theme</span>
			<Button
				v-for="theme in themeOptions"
				:key="theme.value"
				:iconLeft="theme.icon"
				:variant="theme.value === currentTheme ? 'subtle' : 'ghost'"
				@click="setTheme(theme.value as 'light' | 'dark' | 'system')"
			>
				{{ theme.label }}
			</Button>
		</div>

		<Button
			theme="red"
			variant="ghost"
			class="!h-auto w-full !justify-start !rounded-none !px-4 !py-3"
			@click="logoutAndRedirect"
		>
			Sign out
		</Button>
	</div>
</template>
