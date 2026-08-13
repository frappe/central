<script setup lang="ts">
import { PageHeaderBackButton, PageHeaderMobile } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCapabilities } from '@/composables/useCapabilities'
import { useIsMobile } from '@/composables/useIsMobile'
import {
	MOBILE_SETTINGS_BASE,
	SETTINGS_BASE,
	SETTINGS_TABS,
	type SettingsTab,
} from '@/composables/useSettings'

// One settings tab as a full page. Mobile has no room for a dialog with a
// sidebar, so the tabs become routes: /mobile-settings lists them,
// /mobile-settings/:tab is the tab itself, and Back goes where you'd expect.
const route = useRoute()
const router = useRouter()
const { loading, isMember, canEditTeam, canDeleteTeam } = useCapabilities()
const isMobile = useIsMobile()

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
	[tab, allowed, loading, isMobile],
	() => {
		// Widened past the breakpoint (a resize, a rotate): the same tab has a
		// dialog to live in now, so follow it across to the desktop URL.
		if (!isMobile.value) {
			router.replace(`${SETTINGS_BASE}/${tab.value?.value ?? 'profile'}`)
			return
		}
		// An unknown tab is wrong now; a forbidden one is only wrong once
		// capabilities have actually landed, or a refresh would bounce every
		// gated tab before the answer arrives.
		if (!tab.value || (!loading.value && !allowed.value)) {
			router.replace(MOBILE_SETTINGS_BASE)
		}
	},
	{ immediate: true },
)
</script>

<template>
	<!-- No desktop PageHeader and no `sm:hidden`: the watcher above hands this
	     route over to the dialog the moment it isn't mobile, so the page never
	     renders at desktop width. The back button carries the trail up to the
	     hub, which is what the breadcrumbs used to say. -->
	<template v-if="tab && allowed">
		<PageHeaderMobile :title="tab.title">
			<template #prefix>
				<PageHeaderBackButton :to="MOBILE_SETTINGS_BASE" />
			</template>
		</PageHeaderMobile>

		<div class="sm:h-full sm:overflow-y-auto">
			<div class="mx-auto max-w-2xl px-4 py-5 sm:px-6">
				<header class="mb-6">
					<!-- The header already carries the title on mobile; the description
					     is content it can't carry, so that stays. -->
					<h1 class="hidden text-lg font-semibold text-ink-gray-8 sm:block">
						{{ tab.title }}
					</h1>
					<p v-if="tab.description" class="mt-1 text-base text-ink-gray-6">
						{{ tab.description }}
					</p>
				</header>

				<component :is="tab.component" />
			</div>
		</div>
	</template>
</template>
