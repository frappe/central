<script setup lang="ts">
import { Badge, Button, Spinner, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { API, method } from '@/api/methods'
import StorageBuckets from '@/components/addons/StorageBuckets.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServices } from '@/composables/useServices'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { errorToast, errorToastWithAction } from '@/lib/toast'

interface MeteredRow {
	resource_type: string | null
	settlement_mode: string
	period_usage: number
}

const router = useRouter()
const serviceKey = 'storage'

const { canManageServices, canManageBilling } = useCapabilities()
const { offers, offersLoading, instance, loadInstance, activate } =
	useServices()
const { activeTeam } = useSession()
const { setBreadcrumbs } = useBreadcrumbs()

const offer = computed(
	() => offers.value.find((o) => o.name === serviceKey) ?? null,
)
const managedService = computed(() => offer.value?.managed_service ?? null)
const title = computed(() => offer.value?.title ?? 'Service')
const description =
	'S3-compatible buckets for file uploads, backups and static assets.'
watch(title, (value) => setBreadcrumbs([{ label: value }]), { immediate: true })

watch(
	managedService,
	(managed) => {
		if (managed) loadInstance(managed)
	},
	{ immediate: true },
)

const metered = useCall<{ services: MeteredRow[] }, { team: string }>({
	url: method(API.meteredServices),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})

whenTeamReady(() => metered.reload())

const storageRow = computed(() =>
	metered.data?.services.find((s) => s.resource_type === 'Storage'),
)

const storedThisCycle = computed(() => {
	const gigabytes = storageRow.value?.period_usage
	if (!gigabytes) return '0'

	return new Intl.NumberFormat(undefined, {
		notation: 'compact',
		maximumFractionDigits: 1,
	}).format(gigabytes)
})

const settlementLine = computed(() =>
	storageRow.value?.settlement_mode === 'Prepaid Pack'
		? 'Prepaid pack · capped at your bundle'
		: 'Postpaid overage · billed per GB',
)

const planTitle = computed(
	() => instance.value?.plan_title || instance.value?.plan || '—',
)

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
		<div
			v-if="offersLoading && !offer"
			class="flex flex-1 justify-center py-16"
		>
			<Spinner class="size-5 text-ink-gray-5" />
		</div>

		<div v-else-if="!offer" class="flex flex-1 items-center justify-center p-8">
			<EmptyState
				icon="lucide-box"
				title="Service not found"
				description="This service isn't available for your team."
			/>
		</div>

		<template v-else-if="managedService">
			<div class="min-h-0 flex-1 overflow-y-auto">
				<div class="mx-auto w-full max-w-5xl px-6 pb-8 pt-8">
					<!-- No icon tile: it would indent the heading 52px while every section
					     below it starts at the container edge. -->
					<div class="min-w-0">
						<h1 class="text-xl-semibold text-ink-gray-9">{{ title }}</h1>
						<p class="mt-0.5 text-p-base text-ink-gray-5">{{ description }}</p>
					</div>

					<section
						class="mt-6 rounded-6 border border-outline-gray-2 bg-surface-base p-5"
					>
						<div class="flex h-6 items-center justify-between gap-3">
							<span class="text-p-sm text-ink-gray-5">Plan</span>
							<Badge
								:label="instance?.status ?? 'Active'"
								:theme="instance?.status === 'Active' ? 'green' : 'amber'"
								variant="subtle"
							/>
						</div>

						<div class="mt-1.5 flex items-end justify-between gap-4">
							<div class="min-w-0">
								<p class="truncate text-base-semibold text-ink-gray-9">
									{{ planTitle }}
								</p>
								<p class="mt-1 text-p-sm text-ink-gray-5">
									{{ settlementLine }}
								</p>
							</div>

							<div class="shrink-0 text-right">
								<div class="text-lg-semibold tabular-nums text-ink-gray-9">
									{{ storedThisCycle }}
								</div>
								<div class="text-p-xs text-ink-gray-5">GB this cycle</div>
							</div>
						</div>
					</section>

					<!-- Wrapped, not classed: StorageBuckets has a multi-root template
					     (section + dialogs), so a class on it would be dropped. -->
					<div class="mt-8">
						<StorageBuckets
							:managed-service="managedService"
							:can-manage="canManageServices"
						/>
					</div>
				</div>
			</div>
		</template>

		<div v-else class="flex flex-1 items-center justify-center p-8">
			<EmptyState
				icon="lucide-archive"
				:title="`Set up ${title}`"
				description="Activate this add-on for your team, then create as many buckets as you need and share their credentials."
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
	</div>
</template>
