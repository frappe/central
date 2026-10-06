<script setup lang="ts">
import { Button, Spinner, TabButtons } from 'frappe-ui'
import { ref } from 'vue'
import AIApiKeys from '@/components/addons/ai/AIApiKeys.vue'
import AIOverview from '@/components/addons/ai/AIOverview.vue'
import AIUsage from '@/components/addons/ai/AIUsage.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useAI } from '@/composables/useAI'
import { useBreadcrumbs } from '@/composables/useBreadcrumbs'
import { useCapabilities } from '@/composables/useCapabilities'
import { reportError } from '@/lib/feedback'

const { canManageServices } = useCapabilities()
const { ai, aiLoading, models, enable } = useAI()
useBreadcrumbs().setBreadcrumbs([{ label: 'AI' }])

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
</script>

<template>
	<div class="flex h-full flex-col">
		<div v-if="aiLoading && !ai" class="flex flex-1 justify-center py-16">
			<Spinner class="size-5 text-ink-gray-5" />
		</div>

		<template v-else>
			<div class="mx-auto w-full max-w-3xl shrink-0 p-3 md:p-4 lg:mt-6">
				<div class="flex items-start gap-3">
					<span
						class="grid size-10 shrink-0 place-items-center rounded-6 bg-surface-gray-2 text-ink-gray-7"
					>
						<lucide-sparkles class="size-5" />
					</span>
					<div class="min-w-0">
						<h1 class="text-xl font-semibold text-ink-gray-9">AI</h1>
						<p class="mt-0.5 text-p-base text-ink-gray-5">
							Our hosted models and leading upstream models, through OpenAI and
							Anthropic compatible APIs.
						</p>
					</div>
				</div>

				<!-- One row: the tabs, then the open tab's own controls (teleported in). -->
				<div
					v-if="ai?.enabled"
					class="mt-6 flex flex-wrap items-center justify-between gap-2"
				>
					<TabButtons v-model="tab" :options="tabs" />
					<div id="ai-tab-controls" class="contents" />
				</div>
			</div>

			<template v-if="ai?.enabled">
				<AIOverview v-if="tab === 'overview'" />
				<AIUsage v-else-if="tab === 'usage'" />
				<AIApiKeys v-else :models="models" :can-manage="canManageServices" />
			</template>

			<div v-else class="flex flex-1 items-center justify-center p-8">
				<EmptyState
					icon="lucide-sparkles"
					title="Set up AI"
					description="Turn AI on for your team, then create API keys to call the models from your own apps."
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
		</template>
	</div>
</template>
