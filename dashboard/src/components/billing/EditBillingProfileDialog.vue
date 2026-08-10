<script setup lang="ts">
import { Button, Dialog, FormControl, LoadingText, useCall } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'
import { API, method } from '@/api/methods'
import { emailError as validateEmail } from '@/lib/auth'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { errorToast, infoToast, successToast } from '@/lib/toast'
import type { BillingGeo } from '@/types/billing'

// Edit the billing profile — currency (locked after activity), contact, address,
// and India GSTIN — shared by the Billing contact and Tax & compliance cards.
const open = defineModel<boolean>({ default: false })
const { activeTeam } = useSession()
const { currencyLocked, reload: reloadSetup } = useBillingSetup()
// The billing profile is the shared singleton (it reloads on team change and
// after a save via reloadProfile) — no second fetch of the same payload here.
const { profile, reloadProfile } = useBillingOverview()

const geo = useCall<BillingGeo>({
	url: method(API.billingGeo),
	immediate: false,
})
whenTeamReady(() => {
	geo.reload()
})

const FIELDS = [
	'currency',
	'legal_name',
	'email',
	'phone',
	'gstin',
	'address_line1',
	'address_line2',
	'city',
	'state',
	'country',
	'pincode',
] as const
const form = reactive<Record<string, string>>({})
watch(
	() => profile.data,
	(d) => {
		if (!d) return
		const row = d as unknown as Record<string, unknown>
		for (const f of FIELDS) form[f] = row[f]?.toString() ?? ''
	},
	{ immediate: true },
)

const countryOptions = computed(() =>
	(geo.data?.countries ?? []).map((c) => ({ label: c, value: c })),
)
const stateOptions = computed(() => geo.data?.india_states ?? [])
const isIndia = computed(() => form.country === 'India')

// Currency follows the country (India → INR, else USD) — the backend derives it
// on save; we mirror that here so the read-only field updates as they pick a
// country. Never overridden once the currency is locked by billing activity.
const currencyForCountry = (country: string) =>
	country === 'India' ? 'INR' : 'USD'
watch(
	() => form.country,
	(country) => {
		if (!currencyLocked.value) form.currency = currencyForCountry(country ?? '')
	},
)

function optionModel(field: string) {
	return computed<{ label: string; value: string } | null>({
		get: () =>
			form[field] ? { label: form[field], value: form[field] } : null,
		set: (opt) => {
			form[field] = opt?.value ?? ''
		},
	})
}
const countryModel = optionModel('country')
const stateModel = optionModel('state')

// Inline, as-you-type: an entered email must be well-formed (empty is fine —
// the field is optional).
const emailIssue = computed(() =>
	form.email?.trim() ? validateEmail(form.email) : '',
)

// India's term for it is "PIN code"; everywhere else says postal code.
const postalLabel = computed(() => (isIndia.value ? 'PIN code' : 'Postal code'))

const requiredFields = [
	['legal_name', 'Legal name'],
	['address_line1', 'Address line 1'],
	['city', 'City'],
	['country', 'Country'],
] as const
const missingRequired = computed(() =>
	requiredFields
		.filter(([field]) => !form[field]?.trim())
		.map(([, label]) => label),
)

type SaveBillingProfileResponse = {
	setup_complete?: boolean
	missing_labels?: string[]
}
const save = useCall<SaveBillingProfileResponse, Record<string, unknown>>({
	url: method(API.saveBillingProfile),
	method: 'POST',
	immediate: false,
})
async function submit(): Promise<void> {
	if (missingRequired.value.length) {
		infoToast(`Missing: ${missingRequired.value.join(", ")}`)
		return
	}
	try {
		await save.submit({ team: activeTeam.value, ...form })
		await reloadSetup()
		reloadProfile()
		if (save.data?.setup_complete === false) {
			const missing =
				save.data.missing_labels?.join(', ') || 'the required fields'
			infoToast(`Saved. Still missing: ${missing}`)
			return
		}
		successToast('Billing details saved')
		open.value = false
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<Dialog v-model:open="open" title="Billing details" size="2xl">
		<template #default>
			<div v-if="profile.loading && !profile.data" class="space-y-3">
				<LoadingText :lines="6" />
			</div>

			<!-- Not a <form>: frappe-ui's Autocomplete trigger is a type-less (submit)
           button, so a native form would save the profile just by opening/selecting
           Country. The dialog's Save action drives submit() instead. -->
			<div v-else class="space-y-6">
				<div class="space-y-3">
					<h3 class="text-sm-medium text-ink-gray-8">Contact</h3>
					<div class="grid gap-4 sm:grid-cols-2">
						<FormControl
							v-model="form.legal_name"
							label="Legal name"
							placeholder="Acme Technologies Pvt. Ltd."
							required
						/>
						<div>
							<FormControl
								v-model="form.email"
								type="email"
								label="Billing email"
								placeholder="billing@company.com"
							/>
							<p v-if="emailIssue" class="mt-1 text-p-xs text-ink-red-8">
								{{ emailIssue }}
							</p>
						</div>
						<FormControl
							v-model="form.phone"
							label="Phone"
							placeholder="+91 98765 43210"
						/>
					</div>
				</div>

				<!-- Country leads: it decides the state field, the postal label, the
             tax section — and, until locked, the billing currency. Currency is
             a consequence, not a field, so it's stated in the description
             instead of rendered as a dead select. -->
				<div class="space-y-3">
					<h3 class="text-sm-medium text-ink-gray-8">Address</h3>
					<div class="grid gap-4 sm:grid-cols-2">
						<!-- The autocomplete variant swallows `description`/`required`, so
                 the currency note renders as its own line below. -->
						<div class="sm:col-span-2">
							<FormControl
								v-model="countryModel"
								type="autocomplete"
								label="Country"
								placeholder="Select country"
								:options="countryOptions"
							/>
							<p class="mt-1 text-p-xs text-ink-gray-5">
								{{
									currencyLocked
										? `Billed in ${form.currency} — locked, your team already has billing activity.`
										: `Sets your billing currency (${form.currency || 'USD'}).`
								}}
							</p>
						</div>
						<FormControl
							v-model="form.address_line1"
							label="Address line 1"
							placeholder="Street address"
							required
						/>
						<FormControl
							v-model="form.address_line2"
							label="Address line 2"
							placeholder="Suite, floor (optional)"
						/>
						<FormControl v-model="form.city" label="City" required />
						<FormControl
							v-if="isIndia"
							v-model="stateModel"
							type="autocomplete"
							label="State"
							placeholder="Select state"
							:options="stateOptions"
						/>
						<FormControl v-else v-model="form.state" label="State" />
						<FormControl v-model="form.pincode" :label="postalLabel" />
					</div>
				</div>

				<div v-if="isIndia" class="space-y-3">
					<h3 class="text-sm-medium text-ink-gray-8">Tax</h3>
					<div class="sm:max-w-[calc(50%-0.5rem)]">
						<FormControl
							v-model="form.gstin"
							label="GSTIN"
							placeholder="22AAAAA0000A1Z5"
							description="Its first two digits must match the selected state."
						/>
					</div>
				</div>
			</div>
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button label="Cancel" @click="open = false" />
				<Button
					variant="solid"
					label="Save"
					:loading="save.loading"
					@click="submit"
				/>
			</div>
		</template>
	</Dialog>
</template>
