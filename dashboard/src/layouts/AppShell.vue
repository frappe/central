<script setup lang="ts">
import {
	BottomSheet,
	Breadcrumbs,
	DesktopShell,
	Dialogs,
	MobileNav,
	MobileNavItem,
	ToastProvider,
} from 'frappe-ui'
import {
	computed,
	defineAsyncComponent,
	onUnmounted,
	ref,
	watch,
	watchEffect,
} from 'vue'
import { useRoute } from 'vue-router'
import ErrorAlertHost from '@/components/common/ErrorAlertHost.vue'
import ImpersonationBanner from '@/components/navigation/ImpersonationBanner.vue'
import Sidebar from '@/components/navigation/Sidebar.vue'
import NotificationsPanel from '@/components/notifications/NotificationsPanel.vue'
import OnboardingDialog from '@/components/onboarding/OnboardingDialog.vue'
import SettingsModal from '@/components/settings/SettingsModal.vue'
import SuspendedTeamNotice from '@/components/team/SuspendedTeamNotice.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useIsMobile } from '@/composables/useIsMobile'
import { useNotificationsRealtime } from '@/composables/useNotifications'
import {
	openSearch,
	searchOpen,
	useSearchShortcut,
} from '@/composables/useSearch'
import { useSession } from '@/composables/useSession'
import { useSettingsShortcut } from '@/composables/useSettings'
import { teamSwitcherOpen } from '@/composables/useTeamSwitcher'

const SearchDialog = defineAsyncComponent(
	() => import('@/components/search/SearchDialog.vue'),
)
const searchMounted = ref(false)

useNotificationsRealtime()
const { isActiveTeamSuspended } = useSession()
useSearchShortcut()
useSettingsShortcut()

watch(searchOpen, (isOpen) => {
	if (isOpen) searchMounted.value = true
})

const route = useRoute()
const { items, resetBreadcrumbs } = useBreadcrumbs()
const isMobile = useIsMobile()

const mobileNavDrawer = ref(false)
watch(teamSwitcherOpen, (open) => {
	if (open && isMobile.value) mobileNavDrawer.value = true
})
watch(
	() => route.name,
	() => {
		resetBreadcrumbs()
		mobileNavDrawer.value = false
	},
)

watch(isMobile, (mobile) => {
	if (!mobile) mobileNavDrawer.value = false
})

const breadcrumbs = computed(
	() => items.value ?? [{ label: (route.meta.title as string) ?? '' }],
)

const appTitle = document.title
watchEffect(() => {
	document.title = [
		...breadcrumbs.value.map((item) => item.label).reverse(),
		appTitle,
	]
		.filter(Boolean)
		.join(' · ')
})
onUnmounted(() => {
	document.title = appTitle
})
</script>

<template>
	<div v-if="isMobile" class="fixed inset-0 flex flex-col overflow-hidden">
		<ImpersonationBanner />
		<header
			class="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-outline-gray-1 bg-surface-base px-3"
		>
			<button class="flex items-center gap-1" @click="mobileNavDrawer = true">
				<Breadcrumbs :items="breadcrumbs" />
				<span class="lucide-chevron-down size-4 text-ink-gray-5" />
			</button>
			<div id="header-actions" class="flex shrink-0 items-center gap-2" />
		</header>

		<main
			class="min-h-0 flex-1 overflow-hidden"
			style="view-transition-name: page"
		>
			<SuspendedTeamNotice v-if="isActiveTeamSuspended" />
			<router-view v-else />
		</main>

		<MobileNav>
			<MobileNavItem
				label="Home"
				icon="lucide-house"
				route="/home"
				:active="route.name === 'Home'"
			/>
			<MobileNavItem label="Search" icon="lucide-search" @click="openSearch" />
			<NotificationsPanel mobile />
			<MobileNavItem
				label="Settings"
				icon="lucide-settings"
				route="/settings"
			/>
		</MobileNav>
	</div>

	<DesktopShell v-else :scroll="false" class="h-screen">
		<template #sidebar>
			<Sidebar />
		</template>

		<ImpersonationBanner />
		<header
			class="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-outline-gray-1 px-4"
		>
			<Breadcrumbs :items="breadcrumbs" />
			<div id="header-actions" class="flex shrink-0 items-center gap-2" />
		</header>

		<div
			class="min-h-0 flex-1 overflow-hidden"
			style="view-transition-name: page"
		>
			<SuspendedTeamNotice v-if="isActiveTeamSuspended" />
			<router-view v-else />
		</div>
	</DesktopShell>

	<BottomSheet v-model:open="mobileNavDrawer" title="Go to">
		<Sidebar />
	</BottomSheet>

	<ErrorAlertHost />
	<Dialogs />
	<!-- Toasts are reserved for short success and non-actionable status updates. -->
	<ToastProvider />
	<SettingsModal v-if="!isMobile" />
	<SearchDialog v-if="searchMounted" v-model:open="searchOpen" />
	<OnboardingDialog />
</template>
