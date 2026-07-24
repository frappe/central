<script setup lang="ts">
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Breadcrumbs, DesktopShell, ToastProvider } from 'frappe-ui'
import Sidebar from '@/components/navigation/Sidebar.vue'
import { useNotificationsRealtime } from '@/composables/useNotifications'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'

useNotificationsRealtime()

const route = useRoute()
const { items, resetBreadcrumbs } = useBreadcrumbs()

watch(() => route.name, resetBreadcrumbs)

const breadcrumbs = computed(
	() => items.value ?? [{ label: (route.meta.title as string) ?? '' }],
)
</script>

<template>
	<DesktopShell :scroll="false" class="h-screen">
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
</template>
