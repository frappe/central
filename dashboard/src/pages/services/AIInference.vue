<script setup lang="ts">
import { Alert, Button, Dialog, Skeleton, TabButtons, Tooltip } from 'frappe-ui'
import { ref } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import AISettings from '@/components/services/llm/AISettings.vue'
import ApiKeys from '@/components/services/llm/ApiKeys.vue'
import Models from '@/components/services/llm/Models.vue'
import Quickstart from '@/components/services/llm/Quickstart.vue'
import Summary from '@/components/services/llm/Summary.vue'
import Usage from '@/components/services/llm/Usage.vue'
import { useAI } from '@/composables/useAI'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { getErrorMessage, reportError } from '@/lib/feedback'

const { canManageServices } = useCapabilities()
const { activeTeam } = useSession()
const { ai, aiLoading, aiError, reloadAI, enable, minted, dismissMinted } =
	useAI()
useBreadcrumbs().setBreadcrumbs([{ label: 'LLM' }])

const keys = ref<InstanceType<typeof ApiKeys>>()

const TABS = [
	{ label: 'Usage', value: 'usage', glyph: 'lucide-chart-column' },
	{ label: 'API keys', value: 'keys', glyph: 'lucide-key-round' },
	{ label: 'Models', value: 'models', glyph: 'lucide-boxes' },
	{ label: 'Settings', value: 'settings', glyph: 'lucide-settings' },
]
const tab = ref('usage')

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
</script>

<template>
	<div class="h-full overflow-y-auto">
		<Teleport v-if="ai?.enabled && !ai.unavailable" defer to="#header-actions">
			<Button
				icon-left="lucide-code-xml"
				label="How to call"
				@click="keys?.openHelp()"
			/>
			<Tooltip
				v-if="canManageServices"
				:text="
					keys?.atKeyLimit
						? `Your plan allows ${ai.spend?.max_keys} live keys. Revoke one to create another.`
						: ''
				"
			>
				<Button
					variant="solid"
					icon-left="lucide-plus"
					label="Create key"
					:disabled="keys?.atKeyLimit"
					@click="keys?.openCreate()"
				/>
			</Tooltip>
		</Teleport>

		<div
			class="mx-auto flex w-full max-w-5xl flex-col gap-4 px-3 pb-24 pt-3 md:gap-5 md:px-6 md:pt-7"
		>
			<template v-if="aiLoading && !ai">
				<Skeleton class="h-56 rounded-6" />
				<Skeleton class="h-96 rounded-6" />
			</template>

			<EmptyState
				v-else-if="aiError && !ai"
				icon="lucide-cloud-off"
				title="LLM couldn't load"
				:description="getErrorMessage(aiError, 'Try again in a moment.')"
			>
				<template #action>
					<Button label="Retry" @click="reloadAI" />
				</template>
			</EmptyState>

			<Alert
				v-else-if="ai?.unavailable"
				theme="amber"
				title="LLM service is under maintenance"
				description="Your API keys keep working. Usage, keys and limits can't be shown or changed until it is back."
				:primary-action="{ label: 'Retry', onClick: reloadAI }"
			/>

			<template v-else-if="ai?.enabled" :key="activeTeam">
				<Summary
					:can-manage="canManageServices"
					@create="keys?.openCreate()"
					@quickstart="keys?.openHelp()"
				/>

				<div class="flex flex-wrap items-center justify-between gap-2">
					<TabButtons v-model="tab" :options="TABS">
						<template #prefix="{ button }">
							<span class="size-4" :class="button.glyph" aria-hidden="true" />
						</template>
					</TabButtons>
					<div id="ai-tab-controls" class="contents" />
				</div>

				<Usage v-show="tab === 'usage'" :active="tab === 'usage'" />
				<div v-show="tab === 'keys'" class="contents">
					<ApiKeys
						ref="keys"
						:can-manage="canManageServices"
						:active="tab === 'keys'"
					/>
				</div>
				<Models v-show="tab === 'models'" :active="tab === 'models'" />
				<AISettings
					v-show="tab === 'settings'"
					:can-manage="canManageServices"
				/>
			</template>

			<EmptyState
				v-else
				icon="lucide-bot"
				title="Set up LLM"
				description="Our hosted models and leading upstream models, through OpenAI and Anthropic compatible APIs. Enable LLM for your team, then create a key to call them from your own apps."
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

		<Dialog
			:model-value="!!minted"
			:title="minted ? `API key · ${minted.label}` : ''"
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

					<Quickstart
						:gateway-url="minted.gateway_url"
						:models="minted.models"
						:api-key="minted.api_key"
					/>
				</div>
			</template>
		</Dialog>
	</div>
</template>
