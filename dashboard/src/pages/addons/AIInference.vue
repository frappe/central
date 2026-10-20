<script setup lang="ts">
import { Alert, Button, Dialog, Spinner, TabButtons, Tooltip } from 'frappe-ui'
import { ref } from 'vue'
import AIApiKeys from '@/components/addons/ai/AIApiKeys.vue'
import AIOverview from '@/components/addons/ai/AIOverview.vue'
import AIQuickstart from '@/components/addons/ai/AIQuickstart.vue'
import AIUsage from '@/components/addons/ai/AIUsage.vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAI } from '@/composables/useAI'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'

const { canManageServices } = useCapabilities()
const { activeTeam } = useSession()
const {
	ai,
	aiLoading,
	aiError,
	reloadAI,
	enable,
	refreshing,
	refreshUsage,
	minted,
	dismissMinted,
} = useAI()
useBreadcrumbs().setBreadcrumbs([{ label: 'LLM' }])

const tab = ref('overview')
const tabs = [
	{ label: 'Overview', value: 'overview' },
	{ label: 'Usage', value: 'usage' },
	{ label: 'API keys', value: 'keys' },
]

const enabling = ref(false)
const enableAI = async (): Promise<void> => {
	enabling.value = true
	try {
		await enable()
	} catch (e) {
		reportError(e)
	} finally {
		enabling.value = false
	}
}

const refresh = async (): Promise<void> => {
	try {
		await refreshUsage()
		successToast('Usage refreshed.')
	} catch (e) {
		reportError(e, { title: 'Could not refresh usage' })
	}
}
</script>

<template>
	<div class="flex h-full flex-col">
		<!-- The heading, the alert and the tabs belong to a team that has LLM; without it the
		     page is the set-up card alone, as Object Storage is. -->
		<div
			v-if="ai?.enabled"
			class="mx-auto w-full max-w-3xl shrink-0 p-3 md:p-4 lg:mt-6"
		>
			<div class="flex items-start gap-3">
				<span
					class="grid size-10 shrink-0 place-items-center rounded-6 bg-surface-gray-2 text-ink-gray-7"
				>
					<lucide-bot class="size-6" />
				</span>
				<div class="min-w-0">
					<h1 class="text-xl-semibold text-ink-gray-9">LLM</h1>
					<p class="mt-0.5 text-p-base text-ink-gray-5">
						Our hosted models and leading upstream models, through OpenAI and
						Anthropic compatible APIs.
					</p>
				</div>
			</div>

			<!-- Grove down or in maintenance: the gateways keep serving keys, only this page waits. -->
			<Alert
				v-if="ai?.unavailable"
				class="mt-6"
				theme="amber"
				title="LLM service is under maintenance"
				description="Your API keys keep working. Usage, keys and limits can't be shown or changed until it is back."
				:primary-action="{ label: 'Retry', onClick: reloadAI }"
			/>

			<!-- One row: the tabs, then the open tab's own controls (teleported in) and Refresh usage. -->
			<div
				v-else-if="ai?.enabled"
				class="mt-6 flex flex-wrap items-center justify-between gap-2"
			>
				<TabButtons v-model="tab" :options="tabs" />
				<div class="flex flex-wrap items-center gap-2">
					<div id="ai-tab-controls" class="contents" />
					<!-- Icon only: `label` becomes its aria-label, the tooltip shows it. -->
					<Tooltip text="Refresh usage">
						<Button
							label="Refresh usage"
							icon="lucide-refresh-cw"
							:loading="refreshing"
							@click="refresh"
						/>
					</Tooltip>
				</div>
			</div>
		</div>

		<div v-if="aiLoading && !ai" class="flex flex-1 justify-center py-16">
			<Spinner class="size-5 text-ink-gray-5" />
		</div>

		<!-- Grove unreachable is not AI being off: say so, never offer to enable. -->
		<div
			v-else-if="aiError && !ai"
			class="flex flex-1 items-center justify-center p-8"
		>
			<EmptyState
				icon="lucide-cloud-off"
				title="LLM couldn't load"
				:description="getErrorMessage(aiError, 'Try again in a moment.')"
			>
				<template #action>
					<Button label="Retry" @click="reloadAI" />
				</template>
			</EmptyState>
		</div>

		<!-- Keyed on the team: a switch in the sidebar remounts the tab, so it lists that team. -->
		<template v-else-if="ai?.enabled && !ai.unavailable" :key="activeTeam">
			<AIOverview v-if="tab === 'overview'" />
			<AIUsage v-else-if="tab === 'usage'" />
			<AIApiKeys v-else :can-manage="canManageServices" />
		</template>

		<div
			v-else-if="!ai?.enabled"
			class="flex flex-1 items-center justify-center p-8"
		>
			<EmptyState
				icon="lucide-bot"
				title="Set up LLM"
				description="Enable LLM for your team, then create an API key to use the models."
			>
				<template v-if="canManageServices" #action>
					<Button
						variant="solid"
						label="Enable for team"
						icon-left="lucide-zap"
						:loading="enabling"
						@click="enableAI"
					/>
				</template>
			</EmptyState>
		</div>

		<!-- The secret, shown once. It sits outside every branch above, so a reload that comes
		     back unavailable or fails cannot take the dialog away before the key is copied. -->
		<Dialog
			:model-value="!!minted"
			:title="minted ? `API key - ${minted.label}` : ''"
			size="2xl"
			@update:model-value="(open: boolean) => !open && dismissMinted()"
		>
			<template #default>
				<div v-if="minted" class="space-y-5">
					<Alert
						theme="amber"
						title="The key is shown only once"
						description="Copy it somewhere safe. If you lose it, revoke it and create another. It can take a few minutes to start working."
					/>

					<div>
						<label class="mb-1 block text-p-sm-medium text-ink-gray-7">
							API key
						</label>
						<CopyableValue :value="minted.api_key" label="API key" block />
					</div>

					<!-- The examples carry the key and its own gateway, so what is copied runs as is. -->
					<AIQuickstart
						:gateway-url="minted.gateway_url"
						:models="minted.models"
						:api-key="minted.api_key"
					/>
				</div>
			</template>
		</Dialog>
	</div>
</template>
