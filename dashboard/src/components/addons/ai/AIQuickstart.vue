<script setup lang="ts">
import { Select, TabButtons } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import type { AIDialect, AIModel } from '@/types/ai'

// How to call the models: the base URL, and a request, for either API surface. With an
// `apiKey` (a key just minted) the examples carry it; without one they say $API_KEY.
interface Props {
	gatewayUrl: string
	models: AIModel[]
	apiKey?: string
}

const props = defineProps<Props>()

// One key serves both: the gateway takes either SDK's auth header.
const dialect = ref<AIDialect>('openai')
const dialects = [
	{ label: 'OpenAI compatible', value: 'openai' },
	{ label: 'Anthropic compatible', value: 'anthropic' },
]

const language = ref<'curl' | 'python'>('curl')
const languages = [
	{ label: 'curl', value: 'curl' },
	{ label: 'Python', value: 'python' },
]

// The chat example fits a model that answers in text on the chosen surface. A blank
// output list is text.
const chatModels = computed(() =>
	props.models.filter(
		(m) =>
			m.dialects.includes(dialect.value) &&
			(!m.output_modalities.length || m.output_modalities.includes('text')),
	),
)

const selectedModel = ref('')
watch(
	chatModels,
	(models) => {
		const names = models.map((m) => m.name)
		if (!names.includes(selectedModel.value))
			selectedModel.value = names[0] ?? ''
	},
	{ immediate: true },
)

const modelOptions = computed(() =>
	chatModels.value.map((m) => ({ label: m.name, value: m.name })),
)
const model = computed(() => selectedModel.value || 'MODEL_ID')
const key = computed(() => props.apiKey ?? '$API_KEY')

// What each SDK takes as its base URL.
const baseUrl = computed(() =>
	dialect.value === 'openai'
		? `${props.gatewayUrl}/v1`
		: `${props.gatewayUrl}/anthropic`,
)

const examples = computed<Record<AIDialect, Record<'curl' | 'python', string>>>(
	() => ({
		openai: {
			curl: `curl ${baseUrl.value}/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key.value}" \\
  -d '{
    "model": "${model.value}",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
			python: `from openai import OpenAI

client = OpenAI(base_url="${baseUrl.value}", api_key="${key.value}")
response = client.chat.completions.create(
    model="${model.value}",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)`,
		},
		anthropic: {
			curl: `curl ${baseUrl.value}/v1/messages \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: ${key.value}" \\
  -H "anthropic-version: 2023-06-01" \\
  -d '{
    "model": "${model.value}",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
			python: `from anthropic import Anthropic

client = Anthropic(base_url="${baseUrl.value}", api_key="${key.value}")
message = client.messages.create(
    model="${model.value}",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)
print(message.content[0].text)`,
		},
	}),
)

const example = computed(() => examples.value[dialect.value][language.value])
</script>

<template>
	<div class="space-y-4">
		<TabButtons v-model="dialect" :options="dialects" />

		<div>
			<label class="mb-1 block text-p-sm font-medium text-ink-gray-7">
				Base URL
			</label>
			<CopyableValue :value="baseUrl" label="Base URL" block />
		</div>

		<div>
			<div class="mb-1 flex flex-wrap items-center justify-between gap-2">
				<label class="text-p-sm font-medium text-ink-gray-7"
					>Example request</label
				>
				<div class="flex items-center gap-2">
					<Select
						v-if="chatModels.length"
						v-model="selectedModel"
						:options="modelOptions"
						variant="outline"
					/>
					<TabButtons v-model="language" :options="languages" />
				</div>
			</div>
			<CopyableValue
				:value="example"
				label="Example"
				block
				class="whitespace-pre-wrap text-xs leading-relaxed"
			/>
			<p v-if="!apiKey" class="mt-1 text-xs text-ink-gray-5">
				Put one of your API keys in place of
				<code class="font-mono">$API_KEY</code>.
			</p>
		</div>
	</div>
</template>
