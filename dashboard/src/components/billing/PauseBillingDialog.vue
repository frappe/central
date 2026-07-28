<script setup lang="ts">
import { computed } from "vue";
import { Dialog } from "frappe-ui";
import type { SubscriptionRow } from "@/types/billing";

// Confirm for pausing a subscription — pausing stops the server. Controlled by the
// page: pass the pending subscription (or null) via v-model:subscription. A local
// Dialog (like TerminateDialog), not confirmDialog, since this app mounts no global
// <Dialogs /> container.
const props = defineProps<{
	subscription: SubscriptionRow | null;
	loading?: boolean;
}>();

const emit = defineEmits<{
	"update:subscription": [sub: SubscriptionRow | null];
	confirm: [sub: SubscriptionRow];
}>();

const open = computed({
	get: () => !!props.subscription,
	set: (v: boolean) => {
		if (!v) emit("update:subscription", null);
	},
});

const name = computed(
	() =>
		props.subscription?.server ||
		props.subscription?.plan_title ||
		props.subscription?.name ||
		""
);

const dialogOptions = computed(() => ({
	title: "Pause billing",
	message:
		`Pause billing for ${name.value}? This stops the server/VM and the ` +
		`site(s)/services running on it, and stops charges until you resume.`,
	actions: [
		{
			label: "Pause billing",
			variant: "solid" as const,
			loading: props.loading,
			onClick: () => {
				if (props.subscription) emit("confirm", props.subscription);
			},
		},
	],
}));
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:message="dialogOptions.message"
		:actions="dialogOptions.actions"
	/>
</template>
