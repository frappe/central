<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Spinner, TabButtons } from 'frappe-ui'
import EmptyState from '@/components/common/EmptyState.vue'
import AIOverview from '@/components/addons/AIOverview.vue'
import AIApiKeys from '@/components/addons/AIApiKeys.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServices } from '@/composables/useServices'
import { errorToast, errorToastWithAction } from '@/lib/toast'

const router = useRouter()
const serviceKey = 'ai'

const { canManageServices, canManageBilling } = useCapabilities()
const { offers, offersLoading, instance, loadInstance, activate } = useServices()
const { setBreadcrumbs } = useBreadcrumbs()

const offer = computed(() => offers.value.find((o) => o.name === serviceKey) ?? null)
const managedService = computed(() => offer.value?.managed_service ?? null)
const title = computed(() => offer.value?.title ?? 'Service')
const description =
	'Open models on Frappe hardware, through an OpenAI-compatible API.'
watch(title, (value) => setBreadcrumbs([{ label: value }]), { immediate: true })
const models = computed(() => instance.value?.models ?? [])

watch(
	managedService,
	(managed) => {
		if (managed) loadInstance(managed)
	},
	{ immediate: true },
)

const tab = ref('overview')
const tabs = [
	{ label: 'Overview', value: 'overview' },
	{ label: 'API keys', value: 'keys' },
]

const activating = ref(false)
const activateService = async (): Promise<void> => {
	activating.value = true
	try {
		await activate(serviceKey)
	} catch (e) {
		if (canManageBilling.value) {
			errorToastWithAction(e, {
				label: 'Set up billing',
				onClick: () => router.push('/billing'),
			})
		} else {
			errorToast(e)
		}
	} finally {
		activating.value = false
	}
}
</script>

<template>
	<div class="flex h-full flex-col">
		<div v-if="offersLoading && !offer" class="flex flex-1 justify-center py-16">
			<Spinner class="size-5 text-ink-gray-5" />
		</div>

		<div v-else-if="!offer" class="flex flex-1 items-center justify-center p-8">
			<EmptyState
				icon="lucide-box"
				title="Service not found"
				description="This service isn't available for your team."
			/>
		</div>

		<template v-else>
			<div class="mx-auto w-full max-w-3xl shrink-0 px-6 pt-8">
				<div class="flex items-start gap-3">
					<span
						class="grid size-10 shrink-0 place-items-center rounded-lg bg-surface-gray-2 text-ink-gray-7"
					>
						<lucide-sparkles class="size-5" />
					</span>
					<div class="min-w-0">
						<h1 class="text-xl font-semibold text-ink-gray-9">{{ title }}</h1>
						<p class="mt-0.5 text-p-base text-ink-gray-5">{{ description }}</p>
					</div>
				</div>

				<TabButtons v-if="managedService" v-model="tab" :options="tabs" class="mt-6" />
			</div>

			<template v-if="managedService">
				<AIOverview v-if="tab === 'overview'" />
				<AIApiKeys
					v-else
					:managed-service="managedService"
					:models="models"
					:can-manage="canManageServices"
				/>
			</template>

			<div v-else class="flex flex-1 items-center justify-center p-8">
				<EmptyState
					icon="lucide-sparkles"
					:title="`Set up ${title}`"
					description="Activate this add-on for your team, then enable it on the sites that need it or generate and use API keys."
				>
					<template v-if="canManageServices" #action>
						<Button
							variant="solid"
							label="Enable for team"
							icon-left="lucide-zap"
							:loading="activating"
							@click="activateService"
						/>
					</template>
				</EmptyState>
			</div>
		</template>
	</div>
</template>
