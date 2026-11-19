<script setup lang="ts">
import { Button, LoadingIndicator } from 'frappe-ui'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AuthErrorMessage from '@/components/auth/AuthErrorMessage.vue'
import ProductLogo from '@/components/auth/ProductLogo.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import RotatingText from '@/components/common/RotatingText.vue'
import { useOpenTrial } from '@/composables/useOpenTrial'
import { formatDate, plural } from '@/lib/format'
import type { OpenTrial } from '@/types/api'

interface OpenTrialCardProps {
	trial: OpenTrial
	/** The product this signup names. */
	productKey: string
	productTitle: string | null
	/** The new product's Setup Messages, shown in turn while its app installs. */
	setupMessages: string[]
}

const props = defineProps<OpenTrialCardProps>()
const emit = defineEmits<{ 'start-over': [] }>()

const router = useRouter()
const {
	trial,
	step,
	error,
	queuePosition,
	installStartedAt,
	installApp,
	resumeInstall,
	openSite,
	deleteSite,
} = useOpenTrial()
trial.value = props.trial

// A clock for the minutes an install has run.
const now = ref(Date.now())
const clock = setInterval(() => (now.value = Date.now()), 15000)
onUnmounted(() => clearInterval(clock))

const pendingDelete = ref<OpenTrial | null>(null)
const newTitle = computed(() => props.productTitle || props.productKey)
const address = computed(() => props.trial.address ?? '')
const busy = computed(() => step.value !== 'idle' && step.value !== 'installed')

const installLines = computed(() => {
	if (queuePosition.value)
		return ['Waiting for another task on your site to finish.']
	const fallback = `Installing ${newTitle.value} on ${address.value}…`
	return props.setupMessages.length ? props.setupMessages : [fallback]
})

const installMinutes = computed(() => {
	if (!installStartedAt.value) return null
	const started = new Date(installStartedAt.value).getTime()
	return Math.max(0, Math.floor((now.value - started) / 60000))
})

// One free site per trial: a signup for another product adds its app to that site.
const kind = computed(() => {
	if (props.trial.state === 'Setting up') return 'setting-up'
	if (props.trial.state === 'Ended') return 'ended'
	return props.productKey === props.trial.product ? 'open' : 'add-app'
})

const heading = computed(() => {
	if (kind.value === 'setting-up')
		return `Your ${props.trial.product_title} site is being set up`
	if (kind.value === 'ended')
		return `Your ${props.trial.product_title} trial has ended`
	if (kind.value === 'open') return 'You already have a free site'
	if (step.value === 'installing') return `Installing ${newTitle.value}`
	if (step.value === 'installed') return `${newTitle.value} is ready`
	return `Add ${newTitle.value} to your free site`
})

const description = computed(() => {
	const endsOn = props.trial.ends_on ? formatDate(props.trial.ends_on) : ''
	const deletesOn = props.trial.deletes_on
		? formatDate(props.trial.deletes_on)
		: ''
	if (kind.value === 'setting-up')
		return 'Your free trial includes one site. Wait for it to finish, then add more apps to it.'
	if (kind.value === 'ended')
		return `${address.value} is stopped. Upgrade before ${deletesOn} to keep it, or delete it to start a new free trial.`
	if (kind.value === 'open')
		return `${address.value} is your free ${props.trial.product_title} site until ${endsOn}.`
	if (step.value === 'installing')
		return 'This usually takes 2 to 4 minutes. Keep this page open.'
	if (step.value === 'installed')
		return `${newTitle.value} is installed on ${address.value}.`
	return `Your free trial includes one site. Install ${newTitle.value} on ${address.value} and use both apps there.`
})

onMounted(() => {
	if (kind.value === 'add-app') resumeInstall(props.productKey)
})

function upgrade(): void {
	router.push({
		path: `/servers/${props.trial.server}`,
		query: { action: 'resize' },
	})
}

function seeProgress(): void {
	const product = props.trial.product
	router.push({
		path: '/onboarding/provisioning',
		query: product ? { product } : {},
	})
}

async function confirmDelete(): Promise<void> {
	pendingDelete.value = null
	if (await deleteSite()) emit('start-over')
}
</script>

<template>
	<h1 class="flex items-center gap-2 text-2xl-semibold text-ink-gray-9">
		<ProductLogo v-if="kind === 'add-app'" />
		<img
			v-else-if="props.trial.product_logo"
			:src="props.trial.product_logo"
			:alt="props.trial.product_title"
			class="size-8 shrink-0 rounded-4 object-contain"
		/>
		{{ heading }}
	</h1>
	<p class="mt-2 text-p-base text-ink-gray-5">{{ description }}</p>

	<div
		v-if="step === 'installing' || step === 'deleting' || step === 'opening'"
		class="mt-8 flex items-center gap-3 rounded-6 bg-surface-gray-2 px-4 py-3"
		aria-live="polite"
	>
		<LoadingIndicator class="size-4 shrink-0 text-ink-gray-6" />
		<div v-if="step === 'installing'" class="min-w-0 flex-1">
			<RotatingText class="text-p-sm text-ink-gray-7" :lines="installLines" />
			<p v-if="installMinutes !== null" class="text-p-xs text-ink-gray-5">
				Running for {{ plural(installMinutes, 'minute') }}
			</p>
		</div>
		<p v-else class="text-p-sm text-ink-gray-7">
			<template v-if="step === 'deleting'">
				Deleting {{ address }}. This takes about a minute.
			</template>
			<template v-else>Opening your site…</template>
		</p>
	</div>

	<AuthErrorMessage
		v-if="error"
		class="mt-6"
		:message="error"
		page="Open trial"
		:context="{ Product: productTitle, Site: address }"
	/>

	<div class="mt-8 space-y-3">
		<template v-if="kind === 'add-app'">
			<Button
				v-if="step === 'installed'"
				variant="solid"
				size="md"
				class="w-full"
				:label="`Open ${newTitle}`"
				@click="openSite(productKey)"
			/>
			<Button
				v-else-if="step === 'idle'"
				variant="solid"
				size="md"
				class="w-full"
				:label="error ? 'Try again' : `Install ${newTitle}`"
				@click="installApp(productKey)"
			/>
			<Button
				v-if="step === 'idle'"
				size="md"
				class="w-full"
				label="Open my site"
				@click="openSite()"
			/>
		</template>

		<Button
			v-else-if="kind === 'open'"
			variant="solid"
			size="md"
			class="w-full"
			label="Open my site"
			:loading="step === 'opening'"
			@click="openSite()"
		/>

		<template v-else-if="kind === 'ended'">
			<Button
				variant="solid"
				size="md"
				class="w-full"
				label="Upgrade and keep my site"
				:disabled="busy"
				@click="upgrade"
			/>
			<Button
				size="md"
				class="w-full"
				theme="red"
				label="Delete it and start over"
				:loading="step === 'deleting'"
				:disabled="busy"
				@click="pendingDelete = trial"
			/>
		</template>

		<Button
			v-else
			variant="solid"
			size="md"
			class="w-full"
			label="See its progress"
			@click="seeProgress"
		/>
	</div>

	<ConfirmDialog
		v-model:target="pendingDelete"
		:title="`Delete ${address}?`"
		message="The site and all its data are deleted. This can't be undone."
		confirm-label="Delete site"
		theme="red"
		@confirm="confirmDelete"
	/>
</template>
