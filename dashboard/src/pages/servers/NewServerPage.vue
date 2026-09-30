<script setup lang="ts">
import { Alert, Button, Select, TabButtons, Tabs, TextInput } from 'frappe-ui'
import { computed } from 'vue'
import ChoiceCards from '@/components/common/ChoiceCards.vue'
import CreationStatusPanel from '@/components/servers/CreationStatusPanel.vue'
import ImageOfferingSelector from '@/components/servers/ImageOfferingSelector.vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerNetworkOptions from '@/components/servers/ServerNetworkOptions.vue'
import ServerSummary from '@/components/servers/ServerSummary.vue'
import SSHKeysField from '@/components/servers/SSHKeysField.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useServerCreation } from '@/composables/useServerCreation'
import { flagEmoji, regionLabel } from '@/lib/serverMap'

const {
	router,
	regions,
	loading,
	name,
	selectedProvider,
	selectedRegion,
	providerOptions,
	providerRegions,
	selectedRegionRow,
	selectProvider,
	selectRegion,
	markers,
	selectedPlan,
	composedConfig,
	groups,
	rateCard,
	available,
	currency,
	capacity,
	plansLoading,
	plansError,
	reloadPlans,
	hasTabs,
	classTabs,
	activeTab,
	flatPresets,
	flatProfile,
	designableProfile,
	nothingToShow,
	regionFull,
	bracketExhausted,
	summary,
	canSubmit,
	submit,
	source,
	snapshotName,
	snapshotOptions,
	snapshotsLoading,
	snapshotsError,
	reloadSnapshots,
	offering,
	offeringOptions,
	imageId,
	image,
	imageOptions,
	imagesLoading,
	imagesError,
	reloadImages,
	sshKeyIds,
	sshRequired,
	hasPublicIpv6,
	isFirewallEnabled,
	action,
	retry,
	editSettings,
	checkNow,
	checking,
	lastCheckedAt,
	stalled,
	submitting,
	submitError,
} = useServerCreation()

const { setBreadcrumbs } = useBreadcrumbs()
setBreadcrumbs([
	{ label: 'Servers', route: { path: '/servers' } },
	{ label: 'New server' },
])

const selectedRegionName = computed(() =>
	selectedRegionRow.value ? regionLabel(selectedRegionRow.value) : '',
)

const regionOptions = computed(() =>
	providerRegions.value.map((r) => ({
		label: regionLabel(r),
		value: r.region,
		description: r.reachable ? undefined : 'Unreachable',
	})),
)
const regionFlags = computed(() =>
	Object.fromEntries(
		providerRegions.value.map((r) => [r.region, flagEmoji(r.country_code)]),
	),
)
</script>

<template>
	<div class="scrollbar-none h-full overflow-y-auto">
		<Teleport defer to="#header-actions">
			<Button label="Cancel" @click="router.push('/servers')" />
		</Teleport>

		<div class="flex flex-col-reverse lg:flex-row">
			<div class="w-full p-4 md:p-6 lg:w-1/2">
				<p v-if="loading" class="text-p-sm text-ink-gray-5">Loading regions…</p>
				<p v-else-if="!regions.length" class="text-p-sm text-ink-gray-5">
					No active regions are available right now.
				</p>

				<div v-else class="space-y-8">
					<section class="grid gap-3 md:grid-cols-2">
						<TextInput
							v-model="name"
							label="Name"
							required
							size="md"
							placeholder="e.g. Acme Production"
							:maxlength="60"
							autofocus
						/>
					</section>

					<section>
						<h2 class="mb-3 text-base-semibold text-ink-gray-8">Provider</h2>
						<ChoiceCards
							:model-value="selectedProvider"
							:options="providerOptions"
							label="Provider"
							@update:model-value="selectProvider"
						>
							<template #icon="{ option }">
								<ProviderAvatar
									:provider="option.value === 'Other' ? null : option.value"
									:size="24"
								/>
							</template>
						</ChoiceCards>
					</section>

					<section class="space-y-3">
						<h2 class="text-base-semibold text-ink-gray-8">Image</h2>
						<TabButtons
							v-model="source"
							:options="[
								{ label: 'Image', value: 'image' },
								{ label: 'Snapshot', value: 'snapshot' },
							]"
						/>
						<template v-if="source === 'snapshot'">
							<p
								v-if="snapshotsLoading"
								role="status"
								class="text-p-sm text-ink-gray-5"
							>
								Loading snapshots…
							</p>
							<Alert
								v-else-if="snapshotsError"
								theme="red"
								title="Couldn't load snapshots"
								:description="snapshotsError"
								:primary-action="{ label: 'Retry snapshots', onClick: reloadSnapshots }"
							/>
							<p
								v-else-if="snapshotOptions.length < 2"
								class="text-p-sm text-ink-gray-5"
							>
								No snapshots are available in this region.
							</p>
							<Select
								v-else
								v-model="snapshotName"
								label="Snapshot"
								size="md"
								:options="snapshotOptions"
							/>
						</template>
						<template v-else>
							<ImageOfferingSelector
								v-if="offeringOptions.length || (!imagesLoading && !imagesError)"
								v-model="offering"
								:options="offeringOptions"
								:disabled="imagesLoading || !selectedRegion"
							/>
							<p
								v-if="imagesLoading"
								role="status"
								class="text-p-sm text-ink-gray-5"
							>
								Loading regional images…
							</p>
							<Alert
								v-else-if="imagesError"
								theme="red"
								title="Couldn't load images"
								:description="imagesError"
								:primary-action="{ label: 'Retry images', onClick: reloadImages }"
							/>
							<p
								v-else-if="imageOptions.length < 2"
								class="text-p-sm text-ink-gray-5"
							>
								This image has no build in this region. Select another image or
								region.
							</p>
						</template>
						<div class="grid gap-3 md:grid-cols-2">
							<Select
								v-if="source === 'image' && imageOptions.length > 1"
								v-model="imageId"
								label="Image build"
								size="md"
								:options="imageOptions"
							/>
							<SSHKeysField
								v-if="image"
								v-model="sshKeyIds"
								:required="sshRequired"
							/>
						</div>
					</section>

					<section v-if="image">
						<h2 class="mb-3 text-base-semibold text-ink-gray-8">Network</h2>
						<ServerNetworkOptions
							v-model:has-public-ipv6="hasPublicIpv6"
							v-model:is-firewall-enabled="isFirewallEnabled"
						/>
					</section>

					<section>
						<div class="mb-3 flex items-center justify-between gap-3">
							<h2 class="text-base-semibold text-ink-gray-8">Region</h2>
							<span class="text-xs text-ink-gray-5"
								>Or pick a pin on the map</span
							>
						</div>
						<ChoiceCards
							:model-value="selectedRegion"
							:options="regionOptions"
							label="Region"
							@update:model-value="selectRegion"
						>
							<template #icon="{ option }">
								<span class="text-xl leading-none" aria-hidden="true">
									{{ regionFlags[option.value] }}
								</span>
							</template>
						</ChoiceCards>
					</section>

					<section>
						<div class="mb-3 flex items-center justify-between gap-3">
							<h2 class="text-base-semibold text-ink-gray-8">Plan</h2>
							<span class="text-xs text-ink-gray-5">Resize anytime</span>
						</div>
						<p v-if="!image" class="text-p-sm text-ink-gray-5">
							{{ source === 'snapshot'
									? 'Select a snapshot to see compatible plans.'
									: 'Select an image build to see compatible plans.' }}
						</p>
						<p v-else-if="plansLoading" class="text-p-sm text-ink-gray-5">
							Loading plans…
						</p>

						<Alert
							v-else-if="plansError"
							theme="red"
							title="Plans aren't available for this image"
							:description="plansError"
							:primary-action="{ label: 'Retry plans', onClick: reloadPlans }"
						/>

						<Alert
							v-else-if="regionFull"
							theme="amber"
							title="This region is at capacity"
							:description="
								[
									`${selectedRegionName} can't fit a new server right now.`,
									'Try another region, or check back shortly.',
									'Capacity frees up as machines are removed.',
								].join(' ')
							"
						/>

						<div
							v-else-if="bracketExhausted"
							class="rounded-6 border border-outline-gray-2 bg-surface-gray-1 px-4 py-3"
						>
							<p class="text-p-sm font-medium text-ink-gray-8">
								You've reached your spending limit
							</p>
							<p class="mt-1 text-p-sm text-ink-gray-5">
								No plans (preset or custom) fit your remaining headroom in this
								region. Remove a server to free some up, or contact support to
								raise your limit.
							</p>
						</div>

						<p v-else-if="nothingToShow" class="text-p-sm text-ink-gray-5">
							No plans are available for this region within your current
							spending limit.
						</p>

						<Tabs v-else-if="hasTabs" v-model="activeTab" :tabs="classTabs">
							<template #tab-panel="{ tab }">
								<PlanGroup
									class="pt-4"
									:presets="groups[tab.value] ?? []"
									:profile="designableProfile(String(tab.value))"
									:rate-card="rateCard"
									:available="available ?? 0"
									:currency="currency ?? 'USD'"
									:capacity="capacity"
									v-model:selected-plan="selectedPlan"
									v-model:composed-config="composedConfig"
								/>
							</template>
						</Tabs>

						<PlanGroup
							v-else
							:presets="flatPresets"
							:profile="flatProfile"
							:rate-card="rateCard"
							:available="available ?? 0"
							:currency="currency ?? 'USD'"
							:capacity="capacity"
							v-model:selected-plan="selectedPlan"
							v-model:composed-config="composedConfig"
						/>
					</section>

					<section v-if="action || submitError">
						<CreationStatusPanel
							v-if="action"
							:action="action"
							:region-label="selectedRegionName"
							:checking="checking"
							:retrying="submitting"
							:stalled="stalled"
							:last-checked-at="lastCheckedAt"
							:check-error="submitError"
							@check="checkNow"
							@retry="retry"
							@edit="editSettings"
						/>
						<Alert
							v-else
							theme="red"
							title="We couldn't create this server"
							:description="submitError"
						/>
					</section>
				</div>
			</div>

			<div
				class="flex flex-col border-b border-outline-gray-1 lg:sticky lg:top-0 lg:h-[calc(100dvh-3rem)] lg:w-1/2 lg:self-start lg:border-b-0 lg:border-l"
			>
				<div
					class="relative m-6 h-72 overflow-hidden rounded-7 border border-outline-gray-2 lg:h-auto lg:flex-1"
				>
					<ServerMap
						:interactive="false"
						:markers="markers"
						:selected-id="selectedRegion"
						@select="selectRegion"
					/>
				</div>
				<ServerSummary v-bind="summary">
					<Button
						v-if="!action"
						variant="solid"
						size="md"
						label="Create server"
						class="w-full"
						:loading="submitting"
						:disabled="!canSubmit"
						@click="submit"
					/>
				</ServerSummary>
			</div>
		</div>
	</div>
</template>
