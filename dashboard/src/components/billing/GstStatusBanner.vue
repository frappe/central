<script setup lang="ts">
import { Alert, useCall } from 'frappe-ui'
import { computed, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { infoToast, reportError } from '@/lib/feedback'

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
	{ queued: boolean; gst_status: string | null; gst_lapsed: boolean },
	{ team: string }
>({
	url: method(API.recheckGstStatus),
	method: 'POST',
	immediate: false,
})

// The portal is asked in the background; the profile carries its answer once in.
const RELOAD_AFTER_SECONDS = [5, 15, 40]
const checking = ref(false)

async function checkAgain(): Promise<void> {
	const result = await recheck.submit({ team: activeTeam.value! })
	// submit() resolves on a server error too, so the error is checked here.
	if (recheck.error) {
		reportError(recheck.error, { title: 'Could not check your GSTIN' })
		return
	}
	if (!result?.queued) {
		infoToast(
			`Checked a moment ago: the GST portal shows your GSTIN as ${(result?.gst_status || 'not active').toLowerCase()}`,
		)
		return
	}
	infoToast(
		'Checking your GSTIN with the GST portal. This updates in a moment.',
	)
	checking.value = true
	RELOAD_AFTER_SECONDS.forEach((seconds, i) =>
		setTimeout(() => {
			reloadProfile()
			if (i === RELOAD_AFTER_SECONDS.length - 1) checking.value = false
		}, seconds * 1000),
	)
}
</script>

<template>
	<Alert
		v-if="show && p"
		theme="red"
		:title="`Your GSTIN is ${status} on the GST portal`"
		:primary-action="canManageBilling ? { label: 'Update GSTIN', onClick: () => $emit('edit') } : undefined"
		:secondary-action="
			canManageBilling ? { label: 'Check again', loading: recheck.loading || checking, onClick: checkAgain } : undefined
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
