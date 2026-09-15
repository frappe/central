<script setup lang="ts">
import { Breadcrumbs, PageHeader, PageHeaderMobile } from 'frappe-ui'
import frappeCloudLogo from '@/assets/fc-logo.svg'
import Sidebar from '@/components/navigation/Sidebar.vue'

// Home is the nav list itself. Every other section page hangs the same list off
// its title as a drawer (NavDrawerTitle); here that would just be the page
// showing itself twice, so the title stays a plain title. Nothing navigates out
// of the top of the stack, which leaves the left slot free for the mark.
</script>

<template>
	<PageHeaderMobile class="sm:hidden" title="Home">
		<template #prefix>
			<img :src="frappeCloudLogo" alt="Frappe Cloud" class="size-6" />
		</template>
	</PageHeaderMobile>

	<PageHeader class="hidden sm:flex">
		<Breadcrumbs :items="[{ label: 'Home', route: { name: 'Home' } }]" />
	</PageHeader>

	<Sidebar is-mobile />
</template>
