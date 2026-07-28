<script setup lang="ts">
import { computed } from "vue";
import { Button, Dropdown, type DropdownOptions } from "frappe-ui";
import type { ServiceApiKey } from "@/composables/useServices";

// Compact row actions for an API key - a ⋯ menu (matching the servers/members lists)
// so the row never overflows. Reveal + Revoke; the row itself also reveals on click.
const props = defineProps<{ apiKey: ServiceApiKey; busy?: boolean }>();

const emit = defineEmits<{
	reveal: [key: ServiceApiKey];
	revoke: [key: ServiceApiKey];
}>();

const options = computed<DropdownOptions>(() => [
	{
		label: "Reveal key",
		icon: "lucide-eye",
		onClick: () => emit("reveal", props.apiKey),
	},
	{
		label: "Revoke",
		icon: "lucide-trash-2",
		theme: "red",
		onClick: () => emit("revoke", props.apiKey),
	},
]);
</script>

<template>
	<Dropdown :options="options" placement="right">
		<template #trigger>
			<Button
				variant="ghost"
				icon="lucide-ellipsis-vertical"
				:loading="busy"
				aria-label="API key actions"
				@click.stop
			/>
		</template>
	</Dropdown>
</template>
