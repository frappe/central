<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute } from "vue-router";
import { Tabs } from "frappe-ui";
import SentInvitationsPanel from "@/components/team/SentInvitationsPanel.vue";
import ReceivedInvitationsPanel from "@/components/team/ReceivedInvitationsPanel.vue";
import { useCapabilities } from "@/composables/useCapabilities";
import { useMyInvitations } from "@/composables/useMyInvitations";

// Sent (invitations this team issued — managers only) and Received (invitations
// addressed to you) are one screen behind tabs. An email deep-link
// (/invitations/:name) and non-managers land on Received.
const route = useRoute();
const { canManageMembers } = useCapabilities();
const { count } = useMyInvitations();

const receivedLabel = computed(() => (count.value ? `Received (${count.value})` : "Received"));

const tabs = computed(() => {
	const received = { label: receivedLabel.value, icon: "lucide-inbox" };
	return canManageMembers.value
		? [{ label: "Sent", icon: "lucide-send" }, received]
		: [received];
});

// Managers default to Sent; everyone else (or an email deep-link) opens Received.
const wantReceived = !!route.params.name || !canManageMembers.value;
const tabIndex = ref(wantReceived && canManageMembers.value ? 1 : 0);
</script>

<template>
	<div class="flex h-full flex-col">
		<Tabs v-model="tabIndex" :tabs="tabs">
			<template #tab-panel="{ tab }">
				<SentInvitationsPanel v-if="tab.label === 'Sent'" />
				<ReceivedInvitationsPanel v-else />
			</template>
		</Tabs>
	</div>
</template>
