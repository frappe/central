<script setup lang="ts">
import { Avatar, Button, ErrorMessage, LoadingText } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import AuthShell from '@/components/auth/AuthShell.vue'
import ValidatedFormControl from '@/components/common/formComponents/ValidatedFormControl.vue'
import PartnerPayerChoice from '@/components/partner/PartnerPayerChoice.vue'
import PartnerTeamPicker from '@/components/partner/PartnerTeamPicker.vue'
import { usePartnerSetup } from '@/composables/usePartnerSetup'
import { queryString, requiredError } from '@/lib/auth'

const route = useRoute()
const link = {
	p: queryString(route.query.p),
	company: queryString(route.query.company),
}
const {
	partner,
	teams,
	chosen,
	chosenTeam,
	payer,
	step,
	loadError,
	signUpPath,
	signInPath,
	busy,
	error,
	goTo,
	createTeam,
	confirm,
} = usePartnerSetup(link)

// The sending site may suggest the company's name. The customer can change it.
const teamName = ref(link.company)
const submitted = ref(false)
const teamNameError = requiredError('Company name')

const requestSummary = computed(() => {
	const pays = payer.value === 'partner' ? ' and pay for its hosting' : ''
	return `${partner.value?.name} will be asked to work with ${chosen.value?.label}${pays}.`
})

function startNewTeam() {
	teamName.value = link.company
	submitted.value = false
	goTo('name-team')
}

function submitTeamName() {
	submitted.value = true
	if (teamNameError(teamName.value)) return
	createTeam(teamName.value)
}
</script>

<template>
	<AuthShell>
		<LoadingText v-if="step === 'loading'" text="Loading" />

		<template v-else-if="step === 'invalid'">
			<h1 class="text-2xl font-semibold text-ink-gray-9">
				This link isn’t valid
			</h1>
			<p class="mt-1 text-p-base text-ink-gray-5">{{ loadError }}</p>
			<Button
				class="mt-8 w-full"
				size="md"
				route="/servers"
				label="Open Frappe Cloud"
			/>
		</template>

		<template v-else-if="partner">
			<div class="flex items-center gap-3">
				<Avatar
					:image="partner.logo ?? undefined"
					:label="partner.name"
					size="2xl"
					shape="square"
				/>
				<span class="text-base font-medium text-ink-gray-7"
					>{{ partner.name }}</span
				>
			</div>

			<template v-if="step === 'welcome'">
				<h1 class="mt-6 text-2xl font-semibold text-ink-gray-9">
					Set up hosting with {{ partner.name }}
				</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					{{ partner.name }}
					will help run your ERPNext site on Frappe Cloud. Create your account
					to get started.
				</p>
				<div class="mt-8 space-y-4">
					<Button
						class="w-full"
						size="md"
						variant="solid"
						:route="signUpPath"
						label="Create an account"
					/>
					<p class="text-center text-p-base text-ink-gray-5">
						Already have an account?
						<RouterLink
							:to="signInPath"
							class="font-medium text-ink-gray-8 hover:underline"
							>Sign in</RouterLink
						>
					</p>
				</div>
			</template>

			<form
				v-else-if="step === 'name-team'"
				class="mt-6"
				novalidate
				@submit.prevent="submitTeamName"
			>
				<h1 class="text-2xl font-semibold text-ink-gray-9">
					Name your company’s account
				</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					Your servers, sites and bills will live here.
				</p>
				<div class="mt-8 space-y-4">
					<ValidatedFormControl
						v-model="teamName"
						label="Company name"
						placeholder="e.g. Northwind"
						autocomplete="organization"
						v-focus
						:validator="teamNameError"
						:submitted="submitted"
					/>
					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						type="submit"
						label="Continue"
						:loading="busy"
					/>
					<Button
						v-if="teams.length"
						class="w-full"
						size="md"
						variant="ghost"
						label="Back"
						:disabled="busy"
						@click="goTo('pick-team')"
					/>
				</div>
			</form>

			<template v-else-if="step === 'pick-team'">
				<h1 class="mt-6 text-2xl font-semibold text-ink-gray-9">
					Which account should {{ partner.name }} work with?
				</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					Pick the account your company’s site will run in.
				</p>
				<PartnerTeamPicker
					v-model="chosenTeam"
					class="mt-8"
					:teams="teams"
					:partner-name="partner.name"
					@create="startNewTeam"
				/>
				<Button
					class="mt-6 w-full"
					size="md"
					variant="solid"
					label="Continue"
					:disabled="!chosen?.available"
					@click="goTo('payer')"
				/>
			</template>

			<template v-else-if="step === 'payer' && chosen">
				<h1 class="mt-6 text-2xl font-semibold text-ink-gray-9">
					You’re working with {{ partner.name }}
				</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					For {{ chosen.label }}. Who pays for hosting?
				</p>
				<PartnerPayerChoice
					v-model="payer"
					class="mt-8"
					:partner-name="partner.name"
					:disabled="busy"
				/>
				<div class="mt-6 space-y-2">
					<ErrorMessage v-if="error" :message="error" />
					<Button
						class="w-full"
						size="md"
						variant="solid"
						label="Confirm"
						:loading="busy"
						@click="confirm"
					/>
					<Button
						class="w-full"
						size="md"
						variant="ghost"
						label="Back"
						:disabled="busy"
						@click="goTo('pick-team')"
					/>
				</div>
			</template>

			<template v-else-if="step === 'done' && chosen">
				<h1 class="mt-6 text-2xl font-semibold text-ink-gray-9">
					Request sent to {{ partner.name }}
				</h1>
				<p class="mt-1 text-p-base text-ink-gray-5">
					{{ requestSummary }}
					You’ll get an email when they accept.
				</p>
				<Button
					class="mt-8 w-full"
					size="md"
					variant="solid"
					route="/servers"
					label="Go to your account"
				/>
			</template>
		</template>
	</AuthShell>
</template>
