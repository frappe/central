<script setup lang="ts">
import { computed } from 'vue'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
import TranslatedText from '@/components/common/TranslatedText.vue'
import { money } from '@/lib/format'

// Why no plan can be picked. Only `exhausted` is known to come from the spending limit;
// an empty menu can also mean the region has no plans.
const props = defineProps<{
	exhausted: boolean
	available: number | null | undefined
	currency: string | null | undefined
}>()

// What the team can still add before its spending limit, before tax.
const availableLabel = computed(() =>
	money(props.available ?? 0, props.currency ?? 'USD', {
		trimTrailingZeros: true,
	}),
)
</script>

<template>
	<div
		v-if="exhausted"
		class="rounded-6 border border-outline-gray-2 bg-surface-gray-1 px-4 py-3"
	>
		<p class="text-p-sm-medium text-ink-gray-8">
			{{ (available ?? 0) > 0
					? __('No plan fits your spending limit')
					: __("You've reached your spending limit") }}
		</p>
		<p class="mt-1 text-p-sm text-ink-gray-5">
			<TranslatedText
				:text="__('No plans fit the {0} a month, before tax, left in your spending limit in this region. Remove a server to free some up, or {1} to raise your limit.')"
			>
				<template #0>{{ availableLabel }}</template>
				<template #1>
					<ContactSupportLink :context="{ Topic: 'Higher spending limit' }" />
				</template>
			</TranslatedText>
		</p>
	</div>

	<p v-else class="text-p-sm text-ink-gray-5">
		<TranslatedText
			:text="__('No plans are available in this region right now. Select another region, or {0}.')"
		>
			<template #0>
				<ContactSupportLink :context="{ Topic: 'No plans in region' }" />
			</template>
		</TranslatedText>
	</p>
</template>
