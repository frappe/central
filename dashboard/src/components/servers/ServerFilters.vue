<script setup lang="ts">
import { Combobox } from "frappe-ui";
import type { ServerVisual } from "@/lib/serverMap";

// The top-right status + region filters over the map. Both scope the map pins
// and the panel rows; the page owns the option lists and the resolved filters.
defineProps<{
	statusOptions: { label: string; value: string; dot?: string }[];
	regionOptions: { label: string; value: string }[];
}>();

const statusFilter = defineModel<ServerVisual["key"] | "">("statusFilter", { required: true });
const regionSelection = defineModel<string>("regionSelection", { required: true });
</script>

<template>
	<div class="absolute right-4 top-4 flex items-center gap-2">
		<Combobox
			v-model="statusFilter"
			trigger="button"
			variant="outline"
			size="md"
			:options="statusOptions"
		>
			<!-- Button mode reuses #item-prefix on the trigger when a value is selected. -->
			<template #item-prefix="{ item }">
				<span
					class="size-2 shrink-0 rounded-full transition-colors"
					:style="{ background: item.dot || 'var(--ink-gray-4)' }"
				/>
			</template>
		</Combobox>
		<Combobox
			v-model="regionSelection"
			trigger="button"
			variant="outline"
			size="md"
			:options="regionOptions"
		/>
	</div>
</template>
