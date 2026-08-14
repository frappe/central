<script setup lang="ts">
import { Button, SettingsRow, useColorScheme } from 'frappe-ui'
import { useAppMenu } from '@/composables/useAppMenu'

// Theme also lives in the sidebar's header menu, where it's a shortcut. This is
// its home: the menu is for changing it in passing, settings is for finding it
// when you're looking. The choice is stored per browser, not per account.
const { themeOptions } = useAppMenu()
const { colorScheme, setColorScheme } = useColorScheme()
</script>

<template>
	<SettingsRow title="Theme" description="Applies to this browser only.">
		<div class="flex items-center gap-1">
			<Button
				v-for="theme in themeOptions"
				:key="theme.value"
				:icon-left="theme.icon"
				:variant="theme.value === colorScheme ? 'subtle' : 'ghost'"
				:label="theme.label"
				@click="setColorScheme(theme.value)"
			/>
		</div>
	</SettingsRow>
</template>
