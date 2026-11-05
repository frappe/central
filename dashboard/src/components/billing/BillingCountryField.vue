<script setup lang="ts">
import { Combobox, useCall } from 'frappe-ui'
import { computed, onMounted, ref } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage } from '@/lib/feedback'
import type { BillingGeo } from '@/types/billing'

// Country alone sets the billing currency, so asking it first lets the welcome credit and
// prices show in the right currency before the rest of the billing details.
const { activeTeam } = useSession()
const { profile, currency, currencyLocked, refresh } = useBillingSetup()
const { reloadProfile } = useBillingOverview()

const geo = useCall<BillingGeo>({
	url: method(API.billingGeo),
	immediate: false,
})
whenTeamReady(() => geo.reload())
const countryOptions = computed(() =>
	(geo.data?.countries ?? []).map((country) => ({
		label: country,
		value: country,
	})),
)

const save = useCall<unknown, Record<string, unknown>>({
	url: method(API.saveBillingProfile),
	method: 'POST',
	immediate: false,
})
const country = ref(profile.value?.country ?? '')
const error = ref('')

async function saveCountry(value: string): Promise<void> {
	if (!value || value === profile.value?.country) return
	error.value = ''
	await save.submit({ team: activeTeam.value, country: value })
	if (save.error) {
		error.value = getErrorMessage(save.error, 'Could not save your country.')
		return
	}
	await refresh()
	reloadProfile()
}

function onChange(value: string): void {
	country.value = value
	saveCountry(value)
}

// The browser's time zone is a good first guess for India, the one country with its own
// currency. The field shows the guess, and the user can change it.
onMounted(() => {
	if (country.value) return
	const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
	if (zone === 'Asia/Kolkata' || zone === 'Asia/Calcutta') onChange('India')
})
</script>

<template>
	<div>
		<Combobox
			:model-value="country"
			label="Billing country"
			placeholder="Select country"
			:options="countryOptions"
			:disabled="currencyLocked || save.loading"
			:error="error"
			@update:model-value="onChange"
		/>
		<p v-if="!error" class="mt-1 text-p-xs text-ink-gray-5">
			{{ currencyLocked
					? `Billed in ${currency}: locked by billing activity.`
					: currency
						? `You pay in ${currency}.`
						: 'This sets the currency you pay in.' }}
		</p>
	</div>
</template>
