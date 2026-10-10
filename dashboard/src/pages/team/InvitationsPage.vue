<script setup lang="ts">
import { Tabs } from 'frappe-ui'
import { computed, ref } from 'vue'
import ReceivedInvitationsPanel from '@/components/team/ReceivedInvitationsPanel.vue'
import SentInvitationsPanel from '@/components/team/SentInvitationsPanel.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useMyInvitations } from '@/composables/useMyInvitations'

// Sent (invitations this team issued — managers only) and Received (invitations
// addressed to you) are one screen behind tabs. Non-managers land on Received.
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

const activeTab = ref(canManageMembers.value ? 'sent' : 'received')
</script>

<template>
	<div class="flex h-full flex-col">
		<Tabs v-model="activeTab" :tabs="tabs">
			<template #tab-panel="{ tab }">
				<SentInvitationsPanel v-if="tab.value === 'sent'" />
				<ReceivedInvitationsPanel v-else />
			</template>
		</Tabs>
	</div>
</template>
