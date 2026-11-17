<script setup lang="ts">
import { Combobox, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, isAbortError } from '@/lib/feedback'
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
const country = ref('')
let picked = false
const error = ref('')

async function saveCountry(value: string): Promise<boolean> {
	if (!value || value === profile.value?.country) return true
	error.value = ''
	try {
		await save.submit({ team: activeTeam.value, country: value })
	} catch (e) {
		if (!isAbortError(e))
			error.value = getErrorMessage(e, 'Could not save your country.')
		return false
	}
	await refresh()
	reloadProfile()
	return true
}

// Continue can be pressed while a picked country is still saving; share that save
// rather than sending the same request twice.
let saving: Promise<boolean> | null = null
function saveOnce(value: string): Promise<boolean> {
	saving ??= saveCountry(value).finally(() => {
		saving = null
	})
	return saving
}

function onChange(value: string): void {
	picked = true
	country.value = value
	saveOnce(value)
}

// The browser's time zone is a good first guess for India, the one country with its own
// currency. The field shows the guess; it is saved only when the user goes on.
function guessCountry(): string {
	if (currencyLocked.value) return ''
	const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
	return zone === 'Asia/Kolkata' || zone === 'Asia/Calcutta' ? 'India' : ''
}

// The profile loads after the field mounts: show its country once it arrives, and
// guess only when it has none. A country the user picked is never overwritten.
watch(
	profile,
	(loaded) => {
		if (!loaded || picked) return
		country.value = loaded.country || guessCountry()
	},
	{ immediate: true },
)

// Continue goes on only from a known country state. Without the profile we cannot
// tell whether a country is already saved, so stop and ask the user to retry.
function saveOnContinue(): Promise<boolean> {
	if (saving) return saving
	if (!profile.value) {
		error.value = "Couldn't load your billing details. Try again."
		return Promise.resolve(false)
	}
	error.value = ''
	return saveOnce(country.value)
}

defineExpose({ save: saveOnContinue })
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
