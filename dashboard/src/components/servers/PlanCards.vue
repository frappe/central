<script setup lang="ts">
import { planSpecs, planPrice } from "@/lib/plans";
import type { Plan } from "@/types/api";

// Selectable grid of plan cards for the New Server flow. Used both flat (single
// plan class) and inside a class tab panel (multiple classes); the parent owns
// which plan is selected via v-model.
defineProps<{ plans: Plan[] }>();
const selected = defineModel<string | null>({ required: true });
</script>

<template>
	<div class="grid gap-3 sm:grid-cols-2">
		<button
			v-for="plan in plans"
			:key="plan.plan"
			type="button"
			class="flex flex-col gap-1.5 rounded-lg border px-4 py-3 text-left transition-colors"
			:class="
				selected === plan.plan
					? 'border-outline-gray-4 bg-surface-gray-2'
					: 'border-outline-gray-2 hover:border-outline-gray-3'
			"
			@click="selected = plan.plan"
		>
			<div class="flex items-center justify-between gap-2">
				<span class="font-medium text-ink-gray-9">{{ plan.title }}</span>
				<span class="shrink-0 text-p-sm font-medium text-ink-gray-8">{{
					planPrice(plan)
				}}</span>
			</div>
			<span class="text-p-sm text-ink-gray-5">{{ planSpecs(plan) }}</span>
		</button>
	</div>
</template>
