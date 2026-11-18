<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed } from 'vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { getMissingStateIgstRate } from '@/lib/gst'
import { __ } from '@/lib/translate'

const emit = defineEmits<{ edit: [] }>()
const { activeTeam } = useSession()
const { profile } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const rate = computed(() =>
	getMissingStateIgstRate(profile.data, activeTeam.value),
)
const addState = computed(() =>
	canManageBilling.value
		? { label: __('Add state'), onClick: () => emit('edit') }
		: undefined,
)
</script>

<template>
	<Alert
		v-if="rate"
		theme="amber"
		:title="__('Your bills carry IGST {0} until you add your state.', [`${rate}%`])"
		:primary-action="addState"
	/>
</template>
