<script setup lang="ts">
import { ref } from 'vue'
import { Tabs } from 'frappe-ui'
import MembersPanel from '@/components/team/MembersPanel.vue'
import RolesPanel from '@/components/team/RolesPanel.vue'

// Members and roles are two views of the same thing — who is on the team and what
// each role grants — so they live on one page behind tabs rather than two routes.
const tabIndex = ref(0)
const tabs = [
	{ label: 'Members', icon: 'lucide-users' },
	{ label: 'Roles', icon: 'lucide-shield-check' },
]
</script>

<template>
	<div class="flex h-full flex-col">
		<Tabs v-model="tabIndex" :tabs="tabs">
			<template #tab-panel="{ tab }">
				<MembersPanel v-if="tab.label === 'Members'" />
				<RolesPanel v-else />
			</template>
		</Tabs>
	</div>
</template>

<style scoped>
/* frappe-ui's TabsContent doesn't grow; stretch the active panel so the list
   fills the page and its pagination footer pins to the bottom. */
:deep([role="tabpanel"][data-state="active"]) {
	flex: 1;
	min-height: 0;
}
</style>
