<script setup lang="ts">
import { Alert, Button, Select, TabButtons, Tabs, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import PaymentMethodFlow from '@/components/billing/PaymentMethodFlow.vue'
import ChoiceCards from '@/components/common/ChoiceCards.vue'
import ContactSupportLink from '@/components/common/ContactSupportLink.vue'
import CreateServerButton from '@/components/servers/CreateServerButton.vue'
import CreationStatusPanel from '@/components/servers/CreationStatusPanel.vue'
import ImageOfferingSelector from '@/components/servers/ImageOfferingSelector.vue'
import PlanGroup from '@/components/servers/PlanGroup.vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import ServerNetworkOptions from '@/components/servers/ServerNetworkOptions.vue'
import ServerSummary from '@/components/servers/ServerSummary.vue'
import SSHKeysField from '@/components/servers/SSHKeysField.vue'
import TemplateInputs from '@/components/servers/TemplateInputs.vue'
import TemplateSelector from '@/components/servers/TemplateSelector.vue'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useServerCreation } from '@/composables/useServerCreation'
import { features } from '@/lib/features'
import { flagEmoji, regionLabel } from '@/lib/serverMap'
import { getCreationStage } from '@/lib/status'
import type { ActionStatus } from '@/types/serverCreation'

const {
	router,
	regions,
	loading,
	name,
	selectedRegion,
	selectedRegionRow,
	selectRegion,
	markers,
	selectedPlan,
	composedConfig,
	groups,
	rateCard,
	available,
	currency,
	capacity,
	includedTransferGigabytes,
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
	nameError,
	paymentMethodRequired,
	welcomeCredit,
	source,
	snapshotName,
	snapshotOptions,
	snapshotsLoading,
	snapshotsError,
	reloadSnapshots,
	offering,
	offeringOptions,
	templates,
	isTemplate,
	template,
	templateRequirements,
	templateAnswers,
	templateRequirementsLoading,
	templateRequirementsError,
	reloadTemplateRequirements,
	imageId,
	image,
	imageOptions,
	imagesLoading,
	imagesError,
	reloadImages,
	sshKeyIds,
	hasPublicIpv4,
	ipv4PriceLabel,
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
const paymentFlow = ref<InstanceType<typeof PaymentMethodFlow> | null>(null)

const { setBreadcrumbs } = useBreadcrumbs()
setBreadcrumbs([
	{ label: 'Servers', route: { path: '/servers' } },
	{ label: 'New server' },
])

const selectedRegionName = computed(() =>
	selectedRegionRow.value ? regionLabel(selectedRegionRow.value) : '',
)

const regionOptions = computed(() =>
	regions.value.map((r) => ({
		label: regionLabel(r),
		value: r.region,
		description: r.reachable ? undefined : 'Unreachable',
	})),
)
const regionFlags = computed(() =>
	Object.fromEntries(
		regions.value.map((r) => [r.region, flagEmoji(r.country_code)]),
	),
)

// A stopped request hands the button's place to the alert with its next step.
const isCreationMoving = computed(
	() => !action.value || getCreationStage(action.value.status) !== null,
)
// The button fades out after a request stops, so it keeps the last moving status.
const movingStatus = ref<ActionStatus['status'] | null>(null)
watch(
	() => action.value?.status ?? null,
	(status) => {
		if (!status || getCreationStage(status) !== null)
			movingStatus.value = status
	},
	{ immediate: true },
)
</script>

<template>
	<div class="scrollbar-none h-full overflow-y-auto">
		<Teleport defer to="#header-actions">
			<Button label="Cancel" @click="router.push('/servers')" />
		</Teleport>

		<div class="flex flex-col-reverse lg:flex-row">
			<div class="vt-server-form w-full p-4 md:p-6 lg:w-1/2">
				<p v-if="loading" class="text-p-sm text-ink-gray-5">Loading regions…</p>
				<p v-else-if="!regions.length" class="text-p-sm text-ink-gray-5">
					No regions are accepting new servers right now. Try again later, or
					<ContactSupportLink :context="{ Topic: 'New server' }" />.
				</p>

				<div v-else class="space-y-8">
					<Alert
						v-if="paymentMethodRequired"
						title="Add a payment method to create servers"
						icon="lucide-credit-card"
						:description="
							welcomeCredit
								? `Servers are billed monthly. Add a payment method to get ${welcomeCredit}.`
								: 'Servers are billed monthly to your payment method.'
						"
						:primary-action="{
							label: 'Add payment method',
							onClick: () => paymentFlow?.start(),
						}"
					/>

					<section class="grid gap-3 md:grid-cols-2">
						<TextInput
							v-focus
							v-model="name"
							label="Name"
							required
							:error="nameError"
							size="md"
							placeholder="e.g. Acme Production"
							:maxlength="60"
						/>
					</section>

					<section class="space-y-3">
						<h2 class="text-base-semibold text-ink-gray-8">Image</h2>
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
								No snapshots are available in this region. Select another
								region, or choose Image to create a server without a snapshot.
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
							<template v-else-if="isTemplate">
								<p v-if="!templates.length" class="text-p-sm text-ink-gray-5">
									No templates are available in this region yet. Select another
									image or region.
								</p>
								<TemplateSelector
									v-else
									v-model="imageId"
									:templates="templates"
								/>
							</template>
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
								v-if="source === 'image' && !isTemplate && imageOptions.length > 1"
								v-model="imageId"
								label="Image build"
								size="md"
								:options="imageOptions"
							/>
							<SSHKeysField v-if="image" v-model="sshKeyIds" />
						</div>
					</section>

					<section v-if="template" class="space-y-3">
						<h2 class="text-base-semibold text-ink-gray-8">
							{{ template.title }}
							settings
						</h2>
						<p
							v-if="templateRequirementsLoading"
							role="status"
							class="text-p-sm text-ink-gray-5"
						>
							Loading template settings…
						</p>
						<Alert
							v-else-if="templateRequirementsError"
							theme="red"
							title="Couldn't load template settings"
							:description="templateRequirementsError"
							:primary-action="{
								label: 'Retry settings',
								onClick: reloadTemplateRequirements,
							}"
						/>
						<p
							v-else-if="!templateRequirements?.inputs.length"
							class="text-p-sm text-ink-gray-5"
						>
							This template needs no settings.
						</p>
						<TemplateInputs
							v-else
							v-model="templateAnswers"
							:inputs="templateRequirements.inputs"
						/>
					</section>

					<section
						v-if="
							image &&
							(features.publicIpv4 || features.publicIpv6 || features.firewall)
						"
					>
						<h2 class="mb-3 text-base-semibold text-ink-gray-8">Network</h2>
						<ServerNetworkOptions
							v-model:has-public-ipv4="hasPublicIpv4"
							:ipv4-price-label="ipv4PriceLabel"
							v-model:has-public-ipv6="hasPublicIpv6"
							v-model:is-firewall-enabled="isFirewallEnabled"
						/>
					</section>

					<section>
						<div class="mb-3 flex items-center justify-between gap-3">
							<h2 class="text-base-semibold text-ink-gray-8">Region</h2>
							<span class="text-xs text-ink-gray-5"
								>Or select a region on the map</span
							>
						</div>
						<ChoiceCards
							:model-value="selectedRegion"
							:options="regionOptions"
							label="Region"
							@update:model-value="selectRegion"
						>
							<template #icon="{ option }">
								<span class="text-xl" aria-hidden="true">
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
									: isTemplate
										? 'Select a template to see compatible plans.'
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
							<p class="text-p-sm-medium text-ink-gray-8">
								You've reached your spending limit
							</p>
							<p class="mt-1 text-p-sm text-ink-gray-5">
								No plans fit your remaining spending limit in this region.
								Remove a server to free some up, or
								<ContactSupportLink
									:context="{ Topic: 'Higher spending limit' }"
								/>
								to raise your limit.
							</p>
						</div>

						<p v-else-if="nothingToShow" class="text-p-sm text-ink-gray-5">
							No plans are available for this region within your current
							spending limit. Select another region, or
							<ContactSupportLink
								:context="{ Topic: 'Higher spending limit' }"
							/>
							to review your limit.
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
									:included-transfer-gigabytes="includedTransferGigabytes"
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
							:included-transfer-gigabytes="includedTransferGigabytes"
							v-model:selected-plan="selectedPlan"
							v-model:composed-config="composedConfig"
						/>
					</section>
				</div>
			</div>

			<div
				class="flex flex-col border-b border-outline-gray-1 lg:sticky lg:top-0 lg:h-[calc(100dvh-3rem)] lg:w-1/2 lg:self-start lg:border-b-0 lg:border-l"
			>
				<div
					class="vt-server-map relative m-2 h-72 overflow-hidden rounded-6 border border-outline-gray-1 lg:h-auto lg:flex-1"
				>
					<ServerMap
						:interactive="false"
						:markers="markers"
						:selected-id="selectedRegion"
						@select="selectRegion"
					/>
				</div>
				<ServerSummary class="vt-server-summary" v-bind="summary">
					<div class="space-y-3">
						<Alert
							v-if="submitError && !action"
							theme="red"
							title="We couldn't create this server"
							:description="submitError"
						/>
						<div class="relative">
							<Transition
								leave-active-class="transition duration-150 ease-out"
								leave-to-class="scale-[0.98] opacity-0 blur-[2px]"
							>
								<CreateServerButton
									v-if="isCreationMoving"
									:status="movingStatus"
									:region-label="selectedRegionName"
									:submitting="submitting && !action"
									:disabled="!canSubmit"
									@create="submit"
								/>
							</Transition>
							<CreationStatusPanel
								:action="action"
								:checking="checking"
								:retrying="submitting"
								:stalled="stalled"
								:last-checked-at="lastCheckedAt"
								:check-error="submitError"
								@check="checkNow"
								@retry="retry"
								@edit="editSettings"
							/>
						</div>
					</div>
				</ServerSummary>
			</div>
		</div>
		<PaymentMethodFlow ref="paymentFlow" />
	</div>
</template>
