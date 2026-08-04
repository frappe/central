<script setup lang="ts">
import {
	BottomSheet,
	Breadcrumbs,
	DesktopShell,
	MobileNav,
	MobileNavItem,
	MobileShell,
	ToastProvider,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from '@/components/navigation/Sidebar.vue'
import ChangeTeamDialog from '@/components/team/ChangeTeamDialog.vue'
import { useIsMobile } from '@/composables/common/useIsMobile'
import { useAppMenu } from '@/composables/useAppMenu'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useNotificationsRealtime } from '@/composables/useNotifications'

useNotificationsRealtime()

const route = useRoute()
const { items, resetBreadcrumbs } = useBreadcrumbs()
const isMobile = useIsMobile()
const { changeTeamOpen } = useAppMenu()

const mobileNavDrawer = ref(false)
watch(
	() => route.name,
	() => {
		resetBreadcrumbs()
		mobileNavDrawer.value = false
	},
)

const breadcrumbs = computed(
	() => items.value ?? [{ label: (route.meta.title as string) ?? '' }],
)
</script>

<template>
	<MobileShell v-if="isMobile">
		<header
			class="sticky top-0 z-10 flex h-12 shrink-0 items-center justify-between gap-3 border-b border-outline-gray-1 bg-surface-base px-4"
		>
			<button class="flex items-center gap-1" @click="mobileNavDrawer = true">
				<Breadcrumbs :items="breadcrumbs" />
				<span class="lucide-chevron-down size-4 text-ink-gray-5" />
			</button>
			<div id="header-actions" class="flex shrink-0 items-center gap-2" />
		</header>

		<main class="h-full overflow-hidden">
			<router-view />
		</main>

		<template #nav>
			<MobileNav>
				<MobileNavItem
					label="Home"
					icon="lucide-house"
					to="/home"
					:active="route.name === 'Home'"
				/>
				<MobileNavItem label="Search" icon="lucide-search" />
				<MobileNavItem
					label="Notifications"
					icon="lucide-bell"
					to="/notifications"
					:active="route.name =='Notifications' "
				/>
				<MobileNavItem label="Settings" icon="lucide-settings" to="/settings" />
			</MobileNav>
		</template>

		<BottomSheet v-model:open="mobileNavDrawer">
			<Sidebar is-mobile class="p-4" />
		</BottomSheet>
	</MobileShell>

	<DesktopShell v-else :scroll="false" class="h-screen">
		<template #sidebar>
			<Sidebar />
		</template>

		<header
			class="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-outline-gray-1 px-4 sm:px-6"
		>
			<Breadcrumbs :items="breadcrumbs" />
			<div id="header-actions" class="flex shrink-0 items-center gap-2" />
		</header>

		<div class="min-h-0 flex-1 overflow-hidden">
			<router-view />
		</div>
	</DesktopShell>

	<ToastProvider />
	<ChangeTeamDialog v-model:open="changeTeamOpen" />
</template>
