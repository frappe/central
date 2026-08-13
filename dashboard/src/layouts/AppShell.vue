<script setup lang="ts">
import {
	DesktopShell,
	MobileNav,
	MobileNavItem,
	MobileShell,
	ToastProvider,
} from 'frappe-ui'
import { defineAsyncComponent, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from '@/components/navigation/Sidebar.vue'
import SettingsModal from '@/components/settings/SettingsModal.vue'
import { useIsMobile } from '@/composables/useIsMobile'
import { useNotificationsRealtime } from '@/composables/useNotifications'
import {
	openSearch,
	searchOpen,
	useSearchShortcut,
} from '@/composables/useSearch'

// The search palette builds an index off several team-scoped feeds (servers,
// members, invoices…). Mount it lazily on first open so those fetches never fire
// for a user who never searches; once mounted it stays, so its close animation runs.
const SearchDialog = defineAsyncComponent(
	() => import('@/components/search/SearchDialog.vue'),
)
const searchMounted = ref(false)

useNotificationsRealtime()
useSearchShortcut()

// Keep it mounted once opened so re-opening is instant and the exit transition plays.
watch(searchOpen, (isOpen) => {
	if (isOpen) searchMounted.value = true
})

const route = useRoute()
const isMobile = useIsMobile()
</script>

<template>
	<!-- Neither shell renders a header of its own: both expose a PageHeaderTarget
	     above their scroll region, and each page teleports its own header there.
	     Owning one here instead put it *inside* MobileShell's scroll area, which
	     is what cost every mobile page the bottom 48px behind the nav bar. -->
	<MobileShell v-if="isMobile">
		<router-view />

		<template #nav>
			<MobileNav>
				<MobileNavItem
					label="Home"
					icon="lucide-house"
					to="/home"
					:active="route.name === 'Home'"
				/>
				<MobileNavItem
					label="Search"
					icon="lucide-search"
					@click="openSearch"
				/>
				<MobileNavItem
					label="Notifications"
					icon="lucide-bell"
					to="/notifications"
					:active="route.name === 'Notifications'"
				/>
				<!-- This bar only exists on mobile, so it goes straight to the hub.
				     Pointing at /settings would bounce through the dialog route and
				     land on a tab page instead of the list. -->
				<MobileNavItem
					label="Settings"
					icon="lucide-settings"
					to="/mobile-settings"
					:active="String(route.name ?? '').startsWith('MobileSettings')"
				/>
			</MobileNav>
		</template>
	</MobileShell>

	<!-- scroll=false: the servers map and the split panes own their own overflow,
	     which is exactly the case frappe-ui documents this prop for. -->
	<DesktopShell v-else :scroll="false" class="h-screen">
		<template #sidebar>
			<Sidebar />
		</template>

		<div class="min-h-0 flex-1 overflow-hidden">
			<router-view />
		</div>
	</DesktopShell>

	<ToastProvider />
	<!-- Desktop only: on mobile the same tabs are pages (/mobile-settings/:tab),
	     so the dialog never mounts there. -->
	<SettingsModal v-if="!isMobile" />
	<SearchDialog v-if="searchMounted" v-model:open="searchOpen" />
</template>
