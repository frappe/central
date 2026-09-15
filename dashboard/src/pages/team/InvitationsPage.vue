<script setup lang="ts">
import { Breadcrumbs, PageHeader, PageHeaderMobile, Tabs } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import ReceivedInvitationsPanel from '@/components/team/ReceivedInvitationsPanel.vue'
import SentInvitationsPanel from '@/components/team/SentInvitationsPanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useMyInvitations } from '@/composables/useMyInvitations'

// Sent (invitations this team issued — managers only) and Received (invitations
// addressed to you) are one screen behind tabs. An email deep-link
// (/invitations/:name) and non-managers land on Received.
const route = useRoute()
const { canManageMembers } = useCapabilities()
const { count } = useMyInvitations()

const receivedLabel = computed(() =>
	count.value ? `Received (${count.value})` : 'Received',
)

const tabs = computed(() => {
	const received = {
		label: receivedLabel.value,
		value: 'received',
		icon: 'lucide-inbox',
	}
	return canManageMembers.value
		? [{ label: 'Sent', value: 'sent', icon: 'lucide-send' }, received]
		: [received]
})

// Managers default to Sent; everyone else (or an email deep-link) opens Received.
const wantReceived = !!route.params.name || !canManageMembers.value
const activeTab = ref(wantReceived ? 'received' : 'sent')
</script>

<template>
	<!-- No back button, and no route on the crumb: nothing in the app links here
	     (the sidebar has no Invitations entry and Team doesn't link out to one),
	     so the page is reached cold from the invite email or a typed URL — and
	     three routes share it, so a self-link would have to pick one. -->
	<PageHeaderMobile class="sm:hidden" title="Invitations" />

	<PageHeader class="hidden sm:flex">
		<Breadcrumbs :items="[{ label: 'Invitations' }]" />
	</PageHeader>

	<!-- Desktop-only column: on a phone the tabs fall through to the shell's
	     scroll rather than nesting one of their own. -->
	<div class="sm:flex sm:h-full sm:flex-col">
		<Tabs v-model="activeTab" :tabs="tabs">
			<template #tab-panel="{ tab }">
				<SentInvitationsPanel v-if="tab.value === 'sent'" />
				<ReceivedInvitationsPanel v-else />
			</template>
		</Tabs>
	</div>
</template>
