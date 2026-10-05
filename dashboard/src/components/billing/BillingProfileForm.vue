<script setup lang="ts">
import { Alert, Combobox, LoadingText, TextInput, useCall } from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useAuth } from '@/composables/useAuth'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useBillingSetup } from '@/composables/useBillingSetup'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { emailError as validateEmail } from '@/lib/auth'
import { getErrorMessage, successToast } from '@/lib/feedback'
import type { BillingGeo } from '@/types/billing'

// The billing profile fields: currency (locked after activity), contact, address,
// and India GSTIN. The edit dialog and the onboarding billing step both use it, and
// each puts its own Save button around it.
const { activeTeam, teams } = useSession()
const { currentUser } = useAuth()
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

// A blank legal name and billing email start from the team name and the signed-in
// user. They are only suggestions: nothing is stored until the form is saved.
function resetForm(): void {
	if (!profile.data) return
	const row = profile.data as unknown as Record<string, unknown>
	for (const field of FIELDS) form[field] = row[field]?.toString() ?? ''
	form.legal_name ||=
		teams.value.find((team) => team.name === activeTeam.value)?.label ?? ''
	form.email ||= currentUser.value ?? ''
}

watch(() => profile.data, resetForm, { immediate: true })

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
const formError = ref('')
const submitted = ref(false)

function requiredError(field: string, label: string): string {
	return submitted.value && !form[field]?.trim() ? `${label} is required.` : ''
}

watch(form, () => (formError.value = ''), { deep: true })

type SaveBillingProfileResponse = {
	setup_complete?: boolean
	missing_labels?: string[]
}
const save = useCall<SaveBillingProfileResponse, Record<string, unknown>>({
	url: method(API.saveBillingProfile),
	method: 'POST',
	immediate: false,
})
// Resolves true once the profile is saved and complete; the caller then closes or moves on.
async function submit(): Promise<boolean> {
	submitted.value = true
	if (missingRequired.value.length || emailIssue.value) return false
	try {
		// GSTIN applies to India only, so a value typed before a country change is not kept.
		await save.submit({
			team: activeTeam.value,
			...form,
			gstin: isIndia.value ? form.gstin : '',
		})
		if (save.error) throw save.error
		await reloadSetup()
		reloadProfile()
		if (save.data?.setup_complete === false) {
			const missing =
				save.data.missing_labels?.join(', ') || 'the required fields'
			formError.value = `Saved, but these fields are still required: ${missing}.`
			return false
		}
		successToast('Billing details saved')
		return true
	} catch (e) {
		formError.value = getErrorMessage(e)
		return false
	}
}

defineExpose({ submit, saving: computed(() => save.loading) })
</script>

<template>
	<LoadingText v-if="profile.loading && !profile.data" :lines="6" />

	<div v-else class="space-y-4">
		<Alert v-if="formError" theme="red" :title="formError" />
		<!-- One compact grid, so the form fits the onboarding dialog without a resize.
         Country decides the state field, the postal label, GSTIN and, until
         locked, the billing currency, which is stated under it, not a field. -->
		<div class="grid gap-3 sm:grid-cols-2">
			<TextInput
				v-model="form.legal_name"
				label="Legal name"
				placeholder="Acme Technologies Pvt. Ltd."
				:error="requiredError('legal_name', 'Legal name')"
				required
				autofocus
			/>
			<div>
				<TextInput
					v-model="form.email"
					type="email"
					label="Billing email"
					placeholder="billing@company.com"
				/>
				<p v-if="emailIssue" class="mt-1 text-p-xs text-ink-red-7">
					{{ emailIssue }}
				</p>
			</div>
			<div>
				<Combobox
					v-model="form.country"
					label="Country"
					placeholder="Select country"
					:options="countryOptions"
					:error="requiredError('country', 'Country')"
					required
				/>
				<p class="mt-1 text-p-xs text-ink-gray-5">
					{{ currencyLocked
							? `Billed in ${form.currency}: locked by billing activity.`
							: `Sets your billing currency (${form.currency || 'USD'}).` }}
				</p>
			</div>
			<TextInput
				v-model="form.city"
				label="City"
				:error="requiredError('city', 'City')"
				required
			/>
			<TextInput
				v-model="form.address_line1"
				label="Address line 1"
				placeholder="Street address"
				:error="requiredError('address_line1', 'Address line 1')"
				required
			/>
			<TextInput
				v-model="form.address_line2"
				label="Address line 2"
				placeholder="Suite, floor (optional)"
			/>
			<Combobox
				v-if="isIndia"
				v-model="form.state"
				label="State"
				placeholder="Select state"
				:options="stateOptions"
			/>
			<TextInput v-else v-model="form.state" label="State" />
			<TextInput v-model="form.pincode" :label="postalLabel" />
			<TextInput
				v-model="form.phone"
				label="Phone"
				placeholder="+91 98765 43210"
			/>
			<TextInput
				v-if="isIndia"
				v-model="form.gstin"
				label="GSTIN"
				placeholder="22AAAAA0000A1Z5"
				description="Its first two digits must match the selected state."
			/>
		</div>
	</div>
</template>
