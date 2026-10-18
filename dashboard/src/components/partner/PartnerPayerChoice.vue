<script setup lang="ts">
import { computed } from 'vue'
import ChoiceCards, { type Choice } from '@/components/common/ChoiceCards.vue'
import type { PartnerPayer } from '@/composables/usePartnerSetup'

interface Props {
	modelValue: PartnerPayer
	partnerName: string
	disabled?: boolean
	/** Replaces the note under the partner's option. */
	partnerDescription?: string
}

const props = defineProps<Props>()

const emit = defineEmits<{ 'update:modelValue': [payer: PartnerPayer] }>()

const options = computed<Choice[]>(() => [
	{
		label: 'I’ll pay Frappe Cloud myself',
		value: 'customer',
		description: 'You add a card or credits to your account.',
	},
	{
		label: `${props.partnerName} pays, and bills me`,
		value: 'partner',
		description:
			props.partnerDescription ?? `${props.partnerName} has to accept this.`,
	},
])
</script>

<template>
	<ChoiceCards
		:model-value="modelValue"
		:options="options"
		:columns="1"
		:disabled="disabled"
		label="Who pays for hosting"
		@update:model-value="emit('update:modelValue', $event as PartnerPayer)"
	>
		<template #icon="{ option }">
			<span
				:class="[
					'size-4 shrink-0 text-ink-gray-6',
					option.value === 'partner' ? 'lucide-handshake' : 'lucide-credit-card',
				]"
				aria-hidden="true"
			/>
		</template>
	</ChoiceCards>
</template>
