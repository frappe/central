<script setup lang="ts">
import { Button, useColorScheme } from 'frappe-ui'
import { useAppMenu } from '@/composables/useAppMenu'

// Theme also lives in the sidebar's header menu, where it's a shortcut. This is
// its home: the menu is for changing it in passing, settings is for finding it
// when you're looking. The choice is stored per browser, not per account.
const { themeOptions } = useAppMenu()
const { colorScheme, setColorScheme } = useColorScheme()
</script>

<template>
	<!-- SettingsRow's own layout is a fixed two-column row, and three labelled
	     buttons leave the title column too narrow to read on a phone. Same
	     styling, stacked until there's width for the row. -->
	<div class="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center sm:gap-8">
		<div class="min-w-0 flex-1">
			<div class="text-base-medium block text-ink-gray-8">Theme</div>
			<div class="mt-1 text-base leading-5 text-ink-gray-6">
				Applies to this browser only.
			</div>
		</div>
		<div class="flex shrink-0 items-center gap-1 sm:justify-end">
			<Button
				v-for="theme in themeOptions"
				:key="theme.value"
				:icon-left="theme.icon"
				:variant="theme.value === colorScheme ? 'subtle' : 'ghost'"
				:label="theme.label"
				@click="setColorScheme(theme.value)"
			/>
		</div>
	</div>
</template>
