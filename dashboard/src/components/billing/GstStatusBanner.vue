<script setup lang="ts">
import { Alert, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'

// Shown when the GST portal says the team's GSTIN is not active. Invoices still
// go out, but without the GSTIN, so the customer can't claim input tax credit.
defineEmits<{ edit: [] }>()
const { activeTeam } = useSession()
const { profile, reloadProfile } = useBillingOverview()
const { canManageBilling } = useCapabilities()

const p = computed(() => profile.data)
const show = computed(() => !!p.value?.gst_lapsed)
const status = computed(() => (p.value?.gst_status || '').toLowerCase())

const recheck = useCall<
	{ gst_status: string | null; gst_lapsed: boolean },
	{ team: string }
>({
	url: method(API.recheckGstStatus),
	method: 'POST',
	immediate: false,
	onError: (e: unknown) => errorToast(e, 'Could not check your GSTIN'),
})

async function checkAgain(): Promise<void> {
	const result = await recheck.submit({ team: activeTeam.value! })
	// submit() resolves on a server error too; onError has already said so.
	if (recheck.error) return
	successToast(
		result?.gst_lapsed
			? `The GST portal still shows your GSTIN as ${(result.gst_status || 'not active').toLowerCase()}`
			: 'Your GSTIN is active again',
	)
	reloadProfile()
}
</script>

<template>
	<Alert
		v-if="show && p"
		theme="red"
		:title="`Your GSTIN is ${status} on the GST portal`"
		:primary-action="canManageBilling ? { label: 'Update GSTIN', onClick: () => $emit('edit') } : undefined"
		:secondary-action="
			canManageBilling ? { label: 'Check again', loading: recheck.loading, onClick: checkAgain } : undefined
		"
	>
		<template #description>
			Until it's active, invoices are issued without
			<span class="font-mono">{{ p.gstin }}</span>, so you can't claim input tax
			credit on them<template v-if="p.gst_category === 'SEZ'"
				>, and SEZ zero-rating no longer applies</template
			>. Update your GSTIN, or check again if you've had it restored.
		</template>
	</Alert>
</template>
