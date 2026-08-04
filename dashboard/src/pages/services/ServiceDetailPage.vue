<script setup lang="ts">
import { Button, Spinner, Tabs } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import EmptyState from '@/components/common/EmptyState.vue'
import ApiKeysPanel from '@/components/services/ApiKeysPanel.vue'
import OverviewPanel from '@/components/services/OverviewPanel.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServices } from '@/composables/useServices'
import { errorToast, errorToastWithAction } from '@/lib/toast'

// One service's management surface, reached from the sidebar's Services group.
// Activation (once per team, gated by a billing subscription) is the first step;
// after that the work lives behind tabs — Overview, Sites, API keys.
const route = useRoute()
const router = useRouter()
const serviceKey = computed(() => String(route.params.service))

const { canManageServices, canManageBilling } = useCapabilities()
const { offers, offersLoading, instance, loadInstance, activate } =
	useServices()
const { setBreadcrumbs } = useBreadcrumbs()

const offer = computed(
	() => offers.value.find((o) => o.name === serviceKey.value) ?? null,
)
const managedService = computed(() => offer.value?.managed_service ?? null)
const title = computed(() => offer.value?.title ?? 'Service')
watch(title, (value) => setBreadcrumbs([{ label: value }]), { immediate: true })
const models = computed(() => instance.value?.models ?? [])

watch(
	managedService,
	(managed) => {
		if (managed) loadInstance(managed)
	},
	{ immediate: true },
)

const tabIndex = ref(0)
const tabs = [
	{ label: 'Overview', icon: 'lucide-layout-dashboard' },
	{ label: 'API Keys', icon: 'lucide-key-round' },
]

const activating = ref(false)
async function activateService(): Promise<void> {
	activating.value = true
	try {
		await activate(serviceKey.value)
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
		<Tabs v-if="managedService" v-model="tabIndex" :tabs="tabs">
			<template #tab-panel="{ tab }">
				<OverviewPanel v-if="tab.label === 'Overview'" />
				<ApiKeysPanel
					v-else
					:managed-service="managedService"
					:models="models"
					:can-manage="canManageServices"
				/>
			</template>
		</Tabs>

		<template v-else>
			<div
				v-if="offersLoading && !offer"
				class="flex flex-1 justify-center py-16"
			>
				<Spinner class="size-5 text-ink-gray-5" />
			</div>
			<div
				v-else-if="!offer"
				class="flex flex-1 items-center justify-center p-8"
			>
				<EmptyState
					icon="lucide-box"
					title="Service not found"
					description="This service isn't available for your team."
				/>
			</div>
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

<style scoped>
/* frappe-ui's TabsContent doesn't grow; stretch the active panel so the list
   fills the page and its pagination footer pins to the bottom. */
:deep([role="tabpanel"][data-state="active"]) {
	flex: 1;
	min-height: 0;
}
</style>
