<script setup lang="ts">
import { Alert, Badge, Button, FormControl, TabButtons, Tabs } from 'frappe-ui'
import { computed } from 'vue'
import ChoiceCards from '@/components/common/ChoiceCards.vue'
import FormStep from '@/components/common/FormStep.vue'
import CreationStatusPanel from '@/components/servers/CreationStatusPanel.vue'
import ImageOfferingSelector from '@/components/servers/ImageOfferingSelector.vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import ProviderAvatar from '@/components/servers/ProviderAvatar.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerNetworkOptions from '@/components/servers/ServerNetworkOptions.vue'
import SSHKeysField from '@/components/servers/SSHKeysField.vue'
import { useServerCreation } from '@/composables/useServerCreation'
import { flagEmoji, regionLabel } from '@/lib/serverMap'

const {
	router,
	regions,
	loading,
	name,
	subdomain,
	subdomainEdited,
	selectedProvider,
	selectedRegion,
	hoverRegion,
	providerOptions,
	providerRegions,
	selectedRegionRow,
	editSubdomain,
	resetSubdomain,
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
	ctaLabel,
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
	offeringDescription,
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

const selectedRegionName = computed(() =>
	selectedRegionRow.value ? regionLabel(selectedRegionRow.value) : '',
)
</script>

<template>
	<!-- The shell hands this page a fixed-height pane and never page-scrolls, so the page
	     owns its scrolling: one region for the whole page, at every width. The map sticks
	     beside the form instead of being a second scroll box the wheel dies in. -->
	<div class="scrollbar-none h-full overflow-y-auto">
		<Teleport defer to="#header-actions">
			<Button label="Cancel" @click="router.push('/servers')" />
		</Teleport>

		<div class="flex flex-col-reverse lg:flex-row">
			<!-- Stepped form (left) -->
			<div class="w-full p-4 lg:w-[40rem] lg:shrink-0">
				<p v-if="loading" class="text-p-sm text-ink-gray-5">Loading regions…</p>
				<p v-else-if="!regions.length" class="text-p-sm text-ink-gray-5">
					No active regions are available right now.
				</p>

				<div v-else>
					<FormStep title="Name the server">
						<FormControl
							v-model="name"
							aria-label="Server name"
							type="text"
							placeholder="e.g. Acme Production"
							:maxlength="60"
							class="max-w-xs auto-f"
							autofocus
						/>
						<div class="mt-3 max-w-xs">
							<div class="flex items-center justify-between">
								<label for="subdomain" class="text-p-sm text-ink-gray-7">
									Guest hostname
								</label>
								<button
									v-if="subdomainEdited"
									type="button"
									class="text-p-sm text-ink-gray-5 hover:text-ink-gray-7"
									@click="resetSubdomain"
								>
									Reset
								</button>
							</div>
							<FormControl
								id="subdomain"
								:model-value="subdomain"
								type="text"
								placeholder="acme-production"
								:maxlength="63"
								autocomplete="off"
								autocapitalize="off"
								spellcheck="false"
								class="mt-1"
								@update:model-value="editSubdomain"
							/>
						</div>
					</FormStep>

					<FormStep title="Select a provider">
						<!-- Picking a provider also lands on one of its regions, so the choice
						     goes through selectProvider rather than straight to the ref. -->
						<ChoiceCards
							:model-value="selectedProvider"
							:options="providerOptions"
							label="Select a provider"
							@update:model-value="selectProvider"
						>
							<template #icon="{ option }">
								<ProviderAvatar
									:provider="option.value === 'Other' ? null : option.value"
									:size="28"
								/>
							</template>
						</ChoiceCards>
					</FormStep>

					<FormStep title="Select a region">
						<div class="flex flex-wrap gap-2">
							<Button
								v-for="r in providerRegions"
								:key="r.region"
								size="sm"
								variant="outline"
								:class="[
									'!rounded-6 focus-visible:!ring-1 focus-visible:!ring-outline-gray-4',
									r.region === selectedRegion
										? '!border-outline-gray-4 !bg-surface-gray-1 font-medium !text-ink-gray-9'
										: '',
								]"
								@click="selectRegion(r.region)"
								@mouseenter="hoverRegion = r.region"
								@mouseleave="hoverRegion = null"
							>
								<span class="mr-0.5 text-sm leading-none">
									{{ flagEmoji(r.country_code) }}
								</span>
								{{ regionLabel(r) }}
								<Badge
									v-if="!r.reachable"
									theme="gray"
									variant="subtle"
									label="Unreachable"
									class="ml-1"
								/>
							</Button>
						</div>
					</FormStep>

					<FormStep title="Select an image">
						<div class="space-y-3">
							<!-- Offer the snapshot source only when this region has one to restore. -->
							<TabButtons
								v-if="snapshotOptions.length > 1 || source === 'snapshot'"
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
									No snapshot in this region can be restored. A snapshot
									restores only in the region it was taken in, and a Pilot
									server snapshot cannot be restored yet.
								</p>
								<FormControl
									v-else
									v-model="snapshotName"
									type="select"
									label="Snapshot"
									:options="snapshotOptions"
									class="max-w-xs"
								/>
							</template>
							<template v-else>
								<ImageOfferingSelector
									v-if="offeringOptions.length || (!imagesLoading && !imagesError)"
									v-model="offering"
									:options="offeringOptions"
									:disabled="imagesLoading || !selectedRegion"
								/>
								<p v-if="offeringDescription" class="text-p-sm text-ink-gray-5">
									{{ offeringDescription }}
								</p>
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
								<template v-else-if="imageOptions.length < 2">
									<p class="text-p-sm text-ink-gray-5">
										This image has no build in this region. Select another image
										or region.
									</p>
								</template>
								<FormControl
									v-else
									v-model="imageId"
									type="select"
									label="Image build"
									:options="imageOptions"
									class="max-w-xs"
								/>
							</template>
							<SSHKeysField
								v-if="image"
								v-model="sshKeyIds"
								:required="sshRequired"
							/>
							<ServerNetworkOptions
								v-if="image"
								v-model:has-public-ipv6="hasPublicIpv6"
								v-model:is-firewall-enabled="isFirewallEnabled"
							/>
						</div>
					</FormStep>

					<!-- Presets and a scoped Custom row, split into tabs by profile when needed. -->
					<FormStep title="Select a plan">
						<p v-if="!image" class="text-p-sm text-ink-gray-5">
							Select an image build to see compatible plans.
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
					</FormStep>

					<FormStep last>
						<!-- One request at a time: the status panel replaces the button until
						     the request is finished or abandoned. -->
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

						<template v-else>
							<Alert
								v-if="submitError"
								class="mb-3"
								theme="red"
								title="We couldn't create this server"
								:description="submitError"
							/>

							<p
								v-if="selectedRegionRow"
								class="mb-3 flex items-center gap-1.5 text-p-sm leading-5 text-ink-gray-5"
							>
								<span
									class="lucide-map-pin size-4 shrink-0"
									aria-hidden="true"
								/>
								<span
									>Runs in {{ selectedRegionName }}. Your data lives here.</span
								>
							</p>

							<Button
								variant="solid"
								:label="ctaLabel"
								icon-left="lucide-plus"
								:loading="submitting"
								:disabled="!canSubmit"
								@click="submit"
							/>
						</template>
					</FormStep>
				</div>
			</div>

			<!-- Region map (right): the servers map in picker mode — no pan/zoom, it frames
			     the provider's regions and takes clicks as picks. It sticks to the top of the
			     pane while the form scrolls past it, so it is always available to click. The
			     height is the pane (viewport less the shell header) less this padding. -->
			<div class="p-4 lg:sticky lg:top-0 lg:flex-1 lg:self-start">
				<div
					class="relative h-72 w-full overflow-hidden rounded-7 border border-outline-gray-2 lg:h-[calc(100dvh-5rem)]"
				>
					<ServerMap
						:interactive="false"
						:markers="markers"
						:selected-id="selectedRegion"
						:highlight-id="hoverRegion"
						@select="selectRegion"
					/>
				</div>
			</div>
		</div>
	</div>
</template>
