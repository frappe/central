<script setup lang="ts">
import { Button, ErrorMessage, TextInput } from 'frappe-ui'
import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { API } from '@/api/methods'
import AuthShell from '@/components/auth/AuthShell.vue'
import ProductLogo from '@/components/auth/ProductLogo.vue'
import { useProduct } from '@/composables/useProduct'
import { useTrialOnboarding } from '@/composables/useTrialOnboarding'
import {
	frappeErrorMessage,
	getFrappe,
	methodUrl,
	postFrappe,
} from '@/lib/auth'
import { carriedQuery } from '@/lib/authRedirect'

type CreationStatus = {
	status: string
	error: { message: string } | null
}

type Availability = {
	available: boolean
	reason: string | null
	fqdn: string
	domain: string
}

const route = useRoute()
const router = useRouter()
const { productKey } = useProduct()
const { team, requestKey, prepareTeam, readStatus, resetRequestKey } =
	useTrialOnboarding()
const provisioning = {
	path: '/onboarding/provisioning',
	query: carriedQuery(route.query),
}
const subdomain = ref('')
const domain = ref('')
const checking = ref(false)
const creating = ref(false)
const availability = ref<Availability | null>(null)
const error = ref('')

let debounce: ReturnType<typeof setTimeout> | undefined

onMounted(async () => {
	try {
		await prepareTeam()
	} catch (exception) {
		error.value = frappeErrorMessage(exception, 'Could not set up your team.')
		return
	}
	try {
		const status = await readStatus()
		if (status.site?.claimed)
			return router.replace({
				path: '/servers',
				query: { site: status.site.name },
			})
		if (
			status.site ||
			(status.creation &&
				!['Failed', 'Timed Out'].includes(status.creation.status))
		)
			return router.replace(provisioning)
		if (
			status.creation?.status === 'Failed' ||
			status.creation?.status === 'Timed Out'
		)
			resetRequestKey()
	} catch (exception) {
		error.value = frappeErrorMessage(exception, 'Could not find your trial.')
		requestKey.value = ''
		return
	}
	try {
		const result = await getFrappe<{ domain: string }>(
			methodUrl(API.siteDomain),
			{ team: team.value || undefined },
		)
		domain.value = result.domain
	} catch {
		// Non-fatal: the suffix is cosmetic until the check runs, which returns it too.
	}
})

watch(subdomain, (value) => {
	availability.value = null
	error.value = ''
	clearTimeout(debounce)
	if (!value.trim()) return
	debounce = setTimeout(() => check(value.trim()), 400)
})

// The debounce timer outlives the component if the user navigates away mid-type.
onScopeDispose(() => clearTimeout(debounce))

async function check(value: string) {
	checking.value = true
	try {
		const result = await getFrappe<Availability>(
			methodUrl(API.checkSubdomain),
			{ subdomain: value, team: team.value || undefined },
		)
		// Ignore a stale response if the user kept typing — and leave `checking` alone:
		// a newer request is in flight and owns the spinner.
		if (value !== subdomain.value.trim()) return
		availability.value = result
		if (result.domain) domain.value = result.domain
		checking.value = false
	} catch (exception) {
		if (value !== subdomain.value.trim()) return
		error.value = frappeErrorMessage(exception, 'Could not check that name.')
		checking.value = false
	}
}

async function createSite() {
	if (!availability.value?.available) return
	creating.value = true
	error.value = ''
	try {
		// Central asks the region inside this call, so a refusal comes back here rather
		// than stranding the customer on the waiting page.
		const result = await postFrappe<CreationStatus>(
			methodUrl(API.createTrialSite),
			{
				subdomain: subdomain.value.trim(),
				request_key: requestKey.value,
				team: team.value || undefined,
				product: productKey.value || undefined,
			},
		)
		if (result.error) {
			error.value = result.error.message
			resetRequestKey()
			creating.value = false
			return
		}
		router.push(provisioning)
	} catch (exception) {
		error.value = frappeErrorMessage(exception, 'Could not create your site.')
		creating.value = false
	}
}
</script>

<template>
	<AuthShell show-progress :step="3">
		<h1 class="flex items-center gap-2 text-2xl font-semibold text-ink-gray-9">
			<ProductLogo />
			Name your site
		</h1>
		<p class="mt-2 text-p-base text-ink-gray-5">
			This is the web address you'll use to reach it. You can connect a custom
			domain later.
		</p>

		<form class="mt-8 space-y-4" @submit.prevent="createSite">
			<TextInput
				id="subdomain"
				v-model="subdomain"
				v-focus
				label="Site address"
				size="md"
				placeholder="yourcompany"
				autocomplete="off"
				autocapitalize="off"
				spellcheck="false"
			>
				<template v-if="domain" #suffix>
					<span class="text-base text-ink-gray-5">.{{ domain }}</span>
				</template>
			</TextInput>

			<p v-if="checking" class="text-sm text-ink-gray-5">Checking…</p>
			<p
				v-else-if="availability && !availability.available"
				class="text-sm text-ink-red-6"
			>
				{{ availability.reason }}
			</p>
			<p v-else-if="availability?.available" class="text-sm text-ink-green-7">
				{{ availability.fqdn }}
				is available.
			</p>

			<Button
				type="submit"
				variant="solid"
				size="md"
				class="w-full"
				label="Create my site"
				:loading="creating"
				:disabled="creating || !requestKey || !availability?.available"
			/>
			<ErrorMessage v-if="error" :message="error" />
		</form>
	</AuthShell>
</template>
