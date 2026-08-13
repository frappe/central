<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { SETTINGS_TABS, type SettingsTab } from '@/composables/useSettings'

// One settings tab as a full page. Mobile has no room for a dialog with a
// sidebar, so the tabs become routes: /settings lists them, /settings/:tab is
// the tab itself, and Back goes where you'd expect.
const route = useRoute()
const router = useRouter()
const { setBreadcrumbs } = useBreadcrumbs()
const { loading, isMember, canEditTeam, canDeleteTeam } = useCapabilities()

const tab = computed(() =>
	SETTINGS_TABS.find((t) => t.value === (route.params.tab as SettingsTab)),
)

// An unknown tab, or one this member can't reach, belongs back at the list
// rather than on a blank page.
const allowed = computed(() => {
	if (!tab.value) return false
	if (tab.value.requires === 'member') return isMember.value
	if (tab.value.requires === 'teamAdmin')
		return canEditTeam.value || canDeleteTeam.value
	return true
})

watch(
	[tab, allowed, loading],
	() => {
		// An unknown tab is wrong now; a forbidden one is only wrong once
		// capabilities have actually landed, or a refresh would bounce every
		// gated tab before the answer arrives.
		if (!tab.value || (!loading.value && !allowed.value)) {
			router.replace('/settings')
			return
		}
		setBreadcrumbs([
			{ label: 'Settings', route: { path: '/settings' } },
			{ label: tab.value.label },
		])
	},
	{ immediate: true },
)
</script>

<template>
	<div v-if="tab && allowed" class="h-full overflow-y-auto">
		<div class="mx-auto max-w-2xl px-4 py-5 sm:px-6">
			<header class="mb-6">
				<h1 class="text-lg font-semibold text-ink-gray-8">{{ tab.title }}</h1>
				<p v-if="tab.description" class="mt-1 text-base text-ink-gray-6">
					{{ tab.description }}
				</p>
			</header>

			<component :is="tab.component" />
		</div>
	</div>
</template>
