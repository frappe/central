<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Badge, Button, Spinner, Switch } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ConnectionDetailsDialog from '@/components/services/ConnectionDetailsDialog.vue'
import DisableSiteDialog from '@/components/services/DisableSiteDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServices } from '@/composables/useServices'
import { errorToast, errorToastWithAction } from '@/lib/toast'

// One service's management surface. Primary action: enable AI directly on a site.
// Secondary: reveal that site's key + curl for bring-your-own use. Activation (once
// per team, gated by a billing subscription) is the first thing a manager does here.

const route = useRoute()
const router = useRouter()
const serviceKey = computed(() => String(route.params.service))

const { canManageServices, canManageBilling } = useCapabilities()
const {
	offers,
	offersLoading,
	sites,
	instance,
	instanceLoading,
	busySite,
	loadInstance,
	activate,
	enableSite,
	disableSite,
} = useServices()

const offer = computed(() => offers.value.find((o) => o.name === serviceKey.value) ?? null)
const managedService = computed(() => offer.value?.managed_service ?? null)
const title = computed(() => offer.value?.title ?? 'Service')

// Load (and reload) the instance whenever this service's managed record appears —
// covers both first render and the moment activation creates it.
watch(
	managedService,
	(managed) => {
		if (managed) loadInstance(managed)
	},
	{ immediate: true },
)

const enabledSites = computed(() => new Set(instance.value?.enabled_sites ?? []))
const rows = computed(() =>
	sites.value.map((site) => ({
		...site,
		enabled: enabledSites.value.has(site.name),
	})),
)

const activating = ref(false)
async function activateService(): Promise<void> {
	activating.value = true
	try {
		await activate(serviceKey.value)
	} catch (e) {
		// Activation fails when the team's plan doesn't include the service. A billing
		// manager can fix that themselves — send them to Billing (its Metered Services
		// card is where AI Tokens is added); everyone else just sees the message, which
		// already tells them to ask their account administrator.
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

// Connection (BYO) dialog + disable confirm are page-owned modal state.
const connectSite = ref<string | null>(null)
const pendingDisable = ref<string | null>(null)

// The per-site switch: turning on provisions immediately (safe); turning off
// routes through the confirm dialog, since it cuts a live key.
function toggleSite(site: string, enabled: boolean): void {
	if (!managedService.value) return
	if (enabled) enableSite(managedService.value, site)
	else pendingDisable.value = site
}

async function confirmDisable(site: string): Promise<void> {
	pendingDisable.value = null
	if (managedService.value) await disableSite(managedService.value, site)
}
</script>

<template>
	<div class="flex h-full flex-col">
		<PageHeader :title="title">
			<template #actions>
				<Button
					label="Services"
					icon-left="lucide-arrow-left"
					variant="ghost"
					@click="router.push('/services')"
				/>
			</template>
		</PageHeader>

		<div class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
			<div v-if="offersLoading && !offer" class="flex justify-center py-16">
				<Spinner class="size-5 text-ink-gray-5" />
			</div>

			<EmptyState
				v-else-if="!offer"
				icon="lucide-box"
				title="Service not found"
				description="This service isn't available for your team."
			/>

			<!-- Not activated: the one deliberate, billing-gated first step. -->
			<div v-else-if="!managedService" class="mx-auto max-w-xl">
				<EmptyState
					icon="lucide-sparkles"
					:title="`Set up ${title}`"
					description="Activate this add-on for your team, then enable it on the sites that need it. Requires an active AI plan subscription."
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

			<!-- Activated: overview + the per-site surface. -->
			<div v-else class="mx-auto max-w-3xl space-y-6">
				<!-- Overview -->
				<section
					class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5"
				>
					<div class="flex items-start justify-between gap-3">
						<div>
							<h2 class="text-base font-semibold text-ink-gray-9">Overview</h2>
							<p class="mt-1 text-p-sm text-ink-gray-5">
								Plan: {{ instance?.plan_title || instance?.plan || '—' }}
							</p>
						</div>
						<Badge
							:label="instance?.status ?? 'Active'"
							:theme="instance?.status === 'Active' ? 'green' : 'orange'"
							variant="subtle"
						/>
					</div>

					<div class="mt-4">
						<p class="mb-2 text-p-sm font-medium text-ink-gray-7">Included models</p>
						<div v-if="instance?.models.length" class="flex flex-wrap gap-2">
							<Badge
								v-for="m in instance.models"
								:key="m.name"
								:label="`${m.name} · ${m.tier}`"
								theme="gray"
								variant="subtle"
							/>
						</div>
						<p v-else class="text-p-sm text-ink-gray-5">
							No models yet — they appear once your plan grants a tier and the
							provider has published models.
						</p>
					</div>

					<button
						class="mt-4 inline-flex items-center gap-1 text-p-sm font-medium text-ink-gray-7 hover:text-ink-gray-9"
						@click="router.push('/billing')"
					>
						View token usage in Billing
						<span class="lucide-arrow-up-right size-3.5" />
					</button>
				</section>

				<!-- Sites (primary action) -->
				<section
					class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5"
				>
					<div class="flex items-center justify-between gap-3">
						<h2 class="text-base font-semibold text-ink-gray-9">Your sites</h2>
						<Spinner v-if="instanceLoading" class="size-4 text-ink-gray-4" />
					</div>
					<p class="mt-1 text-p-sm text-ink-gray-5">
						Enable AI on a site and it works out of the box. Reveal the key to use it
						from your own apps.
					</p>

					<div
						v-if="!sites.length"
						class="mt-4 py-6 text-center text-p-sm text-ink-gray-5"
					>
						No sites in this team yet.
					</div>

					<ul v-else class="mt-4 divide-y divide-outline-gray-1">
						<li
							v-for="row in rows"
							:key="row.name"
							class="flex items-center gap-3 py-3"
						>
							<span
								class="size-2 shrink-0 rounded-full"
								:class="row.enabled ? 'bg-surface-green-3' : 'bg-surface-gray-4'"
							/>
							<div class="min-w-0 flex-1">
								<p class="truncate text-sm font-medium text-ink-gray-8">
									{{ row.name }}
								</p>
								<p class="truncate text-xs text-ink-gray-5">
									{{ row.enabled ? 'AI enabled' : 'Not enabled' }}
								</p>
							</div>

							<!-- Reveal the key for external use, only once the site is on. -->
							<Button
								v-if="row.enabled && canManageServices"
								label="Connect"
								icon-left="lucide-terminal"
								variant="subtle"
								@click="connectSite = row.name"
							/>
							<Spinner v-if="busySite === row.name" class="size-4 text-ink-gray-4" />
							<!-- Manager: the switch turns AI on/off for this site. -->
							<Switch
								v-if="canManageServices"
								:model-value="row.enabled"
								:disabled="busySite === row.name"
								@update:model-value="(v: boolean) => toggleSite(row.name, v)"
							/>
							<!-- Viewer: read-only status. -->
							<Badge
								v-else-if="row.enabled"
								label="Enabled"
								theme="green"
								variant="subtle"
							/>
						</li>
					</ul>
				</section>
			</div>
		</div>

		<ConnectionDetailsDialog
			v-if="managedService && connectSite"
			:open="!!connectSite"
			:managed-service="managedService"
			:site="connectSite"
			:models="instance?.models ?? []"
			@update:open="
				(v) => {
					if (!v) connectSite = null
				}
			"
		/>

		<DisableSiteDialog
			v-model:site="pendingDisable"
			:loading="busySite === pendingDisable"
			@confirm="confirmDisable"
		/>
	</div>
</template>
