<script setup lang="ts">
import { Button, Select } from 'frappe-ui'
import { computed, ref } from 'vue'
import type { ServiceModel } from '@/composables/useServices'
import { successToast } from '@/lib/toast'

// Presentational: given a resolved gateway URL + key + the plan's models, render the
// endpoint, a masked/reveal-able key, and a ready-to-run curl. Shared by the site
// Connect dialog and the API-keys flow so there's one copy of this UI.
const props = defineProps<{
	gatewayUrl: string
	apiKey: string
	models: ServiceModel[]
}>()

const revealed = ref(false)
const selectedModel = ref(props.models[0]?.name ?? '')

const modelOptions = computed(() =>
	props.models.length
		? props.models.map((m) => ({
				label: `${m.name} (${m.tier})`,
				value: m.name,
			}))
		: [{ label: 'MODEL_ID', value: '' }],
)
const modelId = computed(() => selectedModel.value || 'MODEL_ID')

const maskedKey = computed(() =>
	revealed.value
		? props.apiKey
		: `${props.apiKey.slice(0, 6)}${'•'.repeat(24)}${props.apiKey.slice(-4)}`,
)

// Placeholder token in the shown command (so a screenshot can't leak it); the copy
// button swaps in the real key.
const curlTemplate = computed(
	() => `curl ${props.gatewayUrl}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $LLM_API_KEY" \\
  -d '{
    "model": "${modelId.value}",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
)

async function copy(value: string, label: string): Promise<void> {
	await navigator.clipboard.writeText(value)
	successToast(`${label} copied.`)
}
function copyCurl(): void {
	void copy(curlTemplate.value.replace('$LLM_API_KEY', props.apiKey), 'Command')
}
</script>

<template>
	<div class="space-y-5">
		<p class="text-p-sm text-ink-gray-6">
			Use it from any app, script, or tool. Usage bills to your team just like
			on-site AI.
		</p>

		<!-- Gateway URL -->
		<div>
			<label class="mb-1 block text-p-sm font-medium text-ink-gray-7">
				Gateway URL
			</label>
			<div class="flex items-center gap-2">
				<code
					class="min-w-0 flex-1 truncate rounded-md border border-outline-gray-2 bg-surface-gray-1 px-3 py-2 font-mono text-sm text-ink-gray-8"
				>
					{{ gatewayUrl }}
				</code>
				<Button
					icon="lucide-copy"
					aria-label="Copy gateway URL"
					@click="copy(gatewayUrl, 'Gateway URL')"
				/>
			</div>
		</div>

		<!-- API key -->
		<div>
			<label class="mb-1 block text-p-sm font-medium text-ink-gray-7">
				API Key
			</label>
			<div class="flex items-center gap-2">
				<code
					class="min-w-0 flex-1 truncate rounded-md border border-outline-gray-2 bg-surface-gray-1 px-3 py-2 font-mono text-sm text-ink-gray-8"
				>
					{{ maskedKey }}
				</code>
				<Button
					:icon="revealed ? 'lucide-eye-off' : 'lucide-eye'"
					:aria-label="revealed ? 'Hide key' : 'Reveal key'"
					@click="revealed = !revealed"
				/>
				<Button
					icon="lucide-copy"
					aria-label="Copy API key"
					@click="copy(apiKey, 'API key')"
				/>
			</div>
			<p class="mt-1 text-xs text-ink-gray-5">
				Treat it like a password. Revocable on its own.
			</p>
		</div>

		<!-- Curl example -->
		<div>
			<div class="mb-1 flex items-center justify-between gap-2">
				<label class="text-p-sm font-medium text-ink-gray-7">
					Example request
				</label>
				<Select
					v-if="models.length"
					v-model="selectedModel"
					:options="modelOptions"
					size="sm"
					variant="outline"
				/>
			</div>
			<div class="relative">
				<pre
					class="overflow-x-auto rounded-md border border-outline-gray-2 bg-surface-gray-2 p-3 pr-12 font-mono text-xs leading-relaxed text-ink-gray-8"
				>{{ curlTemplate }}</pre>
				<Button
					class="absolute right-2 top-2"
					icon="lucide-copy"
					size="sm"
					aria-label="Copy command"
					@click="copyCurl"
				/>
			</div>
			<p class="mt-1 text-xs text-ink-gray-5">
				Copy runs with your key filled in; the shown command keeps it as
				<code class="font-mono">$LLM_API_KEY</code>.
			</p>
		</div>
	</div>
</template>
