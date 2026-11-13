<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed } from 'vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { __ } from '@/lib/translate'

// A complete Indian profile with no state is charged IGST. Only a member who can
// edit the billing details is asked to add the state. A team charged no GST has no
// rate, so it sees no banner.
defineEmits<{ edit: [] }>()
const { profile } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const show = computed(
	() =>
		canManageBilling.value &&
		!!profile.data?.complete &&
		!!profile.data?.igst_rate,
)
const rate = computed(() => `${profile.data?.igst_rate}%`)
</script>

<template>
	<Alert
		v-if="show"
		theme="amber"
		:title="__('Your bills carry IGST {0} until you add your state.', [rate])"
		:primary-action="{ label: __('Add state'), onClick: () => $emit('edit') }"
	/>
</template>
