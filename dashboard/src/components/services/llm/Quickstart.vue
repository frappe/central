<script setup lang="ts">
import { Select, TabButtons } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import type { AIDialect, AIModel } from '@/types/ai'

interface Props {
	gatewayUrl: string
	models: AIModel[]
	apiKey?: string
}

const props = defineProps<Props>()

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

// Models the example can show: chat (text out) and embeddings. Grove lists embeddings on the
// OpenAI surface only, so the dialect filter keeps them off the Anthropic tab by itself.
const shownModels = computed(() =>
	props.models.filter(
		(m) =>
			m.dialects.includes(dialect.value) &&
			(!m.output_modalities.length ||
				m.output_modalities.includes('text') ||
				m.output_modalities.includes('embeddings')),
	),
)

const selectedModel = ref('')
watch(
	shownModels,
	(models) => {
		const names = models.map((m) => m.name)
		if (!names.includes(selectedModel.value))
			selectedModel.value = names[0] ?? ''
	},
	{ immediate: true },
)

const modelOptions = computed(() =>
	shownModels.value.map((m) => ({ label: m.name, value: m.name })),
)
const model = computed(() => selectedModel.value || 'MODEL_ID')
const embeds = computed(() =>
	shownModels.value
		.find((m) => m.name === selectedModel.value)
		?.output_modalities.includes('embeddings'),
)
const key = computed(() => props.apiKey ?? '$API_KEY')

const baseUrl = computed(() =>
	dialect.value === 'openai'
		? `${props.gatewayUrl}/openai/v1`
		: `${props.gatewayUrl}/anthropic`,
)

const embeddingExamples = computed<Record<'curl' | 'python', string>>(() => ({
	curl: `curl ${baseUrl.value}/embeddings \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer ${key.value}" \\
  -d '{
    "model": "${model.value}",
    "input": "Hello"
  }'`,
	python: `from openai import OpenAI

client = OpenAI(base_url="${baseUrl.value}", api_key="${key.value}")
response = client.embeddings.create(
    model="${model.value}",
    input="Hello",
)
print(response.data[0].embedding)`,
}))

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

const example = computed(() =>
	embeds.value
		? embeddingExamples.value[language.value]
		: examples.value[dialect.value][language.value],
)
</script>

<template>
	<div class="space-y-4">
		<TabButtons v-model="dialect" :options="dialects" />

		<div>
			<label class="mb-1 block text-p-sm-medium text-ink-gray-7">
				Base URL
			</label>
			<CopyableValue :value="baseUrl" label="Base URL" block />
		</div>

		<div>
			<div class="mb-1 flex flex-wrap items-center justify-between gap-2">
				<label class="text-p-sm-medium text-ink-gray-7">Example request</label>
				<div class="flex items-center gap-2">
					<Select
						v-if="shownModels.length"
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
				class="whitespace-pre-wrap text-p-xs"
			/>
			<p v-if="!apiKey" class="mt-1 text-xs text-ink-gray-5">
				Put one of your API keys in place of
				<code class="font-mono">$API_KEY</code>.
			</p>
		</div>
	</div>
</template>
