<script setup lang="ts">
import { Breadcrumbs, PageHeader } from 'frappe-ui'
import { onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCapabilities } from '@/composables/useCapabilities'
import { useIsMobile } from '@/composables/useIsMobile'
import {
	MOBILE_SETTINGS_BASE,
	SETTINGS_BASE,
	SETTINGS_TABS,
	type SettingsTab,
	returnFromSettings,
	settingsOpen,
	settingsTab,
} from '@/composables/useSettings'

// Desktop settings are a dialog, but they still get an address. This route
// renders nothing: it exists to keep /settings/:tab and the dialog in step in
// both directions, so Back, Forward and a reload all land on the tab the URL
// names, and picking a tab inside the dialog updates the URL to match.
const route = useRoute()
const router = useRouter()
const isMobile = useIsMobile()

const { loading, isMember, canEditTeam, canDeleteTeam } = useCapabilities()

const known = (value: unknown): value is SettingsTab =>
	SETTINGS_TABS.some((tab) => tab.value === value)

// A tab this member can't reach is as wrong as one that doesn't exist: the
// dialog only renders panels for the tabs it lists, so an ungated slug selects
// nothing and leaves a blank content pane with nothing lit in the sidebar. The
// mobile page has always gated this; when the two presentations split, the
// desktop half lost the check.
const reachable = (value: SettingsTab): boolean => {
	const tab = SETTINGS_TABS.find((t) => t.value === value)
	if (tab?.requires === 'member') return isMember.value
	if (tab?.requires === 'teamAdmin')
		return canEditTeam.value || canDeleteTeam.value
	return true
}

watch(
	[() => route.params.tab, isMobile, loading, isMember, canEditTeam, canDeleteTeam],
	() => {
		const param = route.params.tab
		const tab = known(param) ? param : 'profile'
		// The dialog never mounts on a phone, so this URL would render an empty
		// page there. Hand the same tab to the page stack that does exist.
		if (isMobile.value) {
			router.replace(`${MOBILE_SETTINGS_BASE}/${tab}`)
			return
		}
		// An unknown tab is a typo in the address bar, not a state to render.
		if (!known(param)) {
			router.replace(`${SETTINGS_BASE}/${tab}`)
			return
		}
		// A gated tab is only wrong once capabilities have actually landed, or a
		// reload would bounce every gated tab before the answer arrives.
		if (!loading.value && !reachable(tab)) {
			router.replace(`${SETTINGS_BASE}/profile`)
			return
		}
		settingsTab.value = tab
		settingsOpen.value = true
	},
	{ immediate: true },
)

// A tab picked in the dialog's sidebar is a navigation like any other.
watch(settingsTab, (tab) => {
	if (settingsOpen.value && route.params.tab !== tab) {
		router.replace(`${SETTINGS_BASE}/${tab}`)
	}
})

// Dismissing the dialog (its close button, Esc, the backdrop) leaves this route
// showing nothing, so treat it as leaving settings.
watch(settingsOpen, (open) => {
	if (!open) returnFromSettings()
})

onUnmounted(() => {
	settingsOpen.value = false
})
</script>

<template>
	<!-- The page itself is empty — the dialog is the content. The header strip
	     still gets a crumb so the chrome behind the scrim matches every other
	     desktop page, including when this URL is opened cold and there's no
	     page underneath to return to. Mobile never reaches here. -->
	<PageHeader class="hidden sm:flex">
		<Breadcrumbs :items="[{ label: 'Settings' }]" />
	</PageHeader>
</template>
