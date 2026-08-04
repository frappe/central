<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
	Badge,
	Button,
	Dialog,
	Dropdown,
	FormControl,
	Select,
	type DropdownOptions,
} from 'frappe-ui'

import EmptyState from '@/components/common/EmptyState.vue'

import { useServices } from '@/composables/useServices'
import { errorToast, successToast } from '@/lib/toast'

import type {
	RevealedKey,
	ServiceApiKey,
	ServiceModel,
} from '@/composables/useServices'

const props = defineProps<{
	managedService: string
	models: ServiceModel[]
	canManage: boolean
}>()

const {
	apiKeys,
	apiKeysLoading,
	busyKey,
	loadApiKeys,
	generateApiKey,
	revealKey,
	revokeKey,
} = useServices()

watch(
	() => props.managedService,
	(managed) => {
		if (managed) loadApiKeys(managed)
	},
	{ immediate: true },
)

const revealingName = ref('')

const reveal = async (key: ServiceApiKey): Promise<void> => {
	revealingName.value = key.name
	try {
		details.value = await revealKey(key.name)
	} catch (e) {
		errorToast(e)
	} finally {
		revealingName.value = ''
	}
}
const rowActions = (key: ServiceApiKey): DropdownOptions => {
	return [
		{ label: 'Reveal key', icon: 'lucide-eye', onClick: () => reveal(key) },
		{
			label: 'Revoke',
			icon: 'lucide-trash-2',
			theme: 'red',
			onClick: () => (pendingRevoke.value = key),
		},
	]
}

const generateOpen = ref(false)
const newLabel = ref('')
const generating = ref(false)

const openGenerate = (): void => {
	newLabel.value = ''
	generateOpen.value = true
}

const generate = async (): Promise<void> => {
	const label = newLabel.value.trim()
	if (!label) return

	generating.value = true

	try {
		details.value = await generateApiKey(props.managedService, label)
		generateOpen.value = false
	} catch (e) {
		errorToast(e)
	} finally {
		generating.value = false
	}
}

const details = ref<RevealedKey | null>(null)
const secretRevealed = ref(false)
const selectedModel = ref('')

watch(details, (value) => {
	secretRevealed.value = false
	selectedModel.value = value ? (props.models[0]?.name ?? '') : ''
})

const modelOptions = computed(() =>
	props.models.length
		? props.models.map((m) => ({
				label: `${m.name} (${m.tier})`,
				value: m.name,
			}))
		: [{ label: 'MODEL_ID', value: '' }],
)
const modelId = computed(() => selectedModel.value || 'MODEL_ID')

const maskedKey = computed(() => {
	if (!details.value) return ''
	return secretRevealed.value
		? details.value.api_key
		: `${details.value.api_key.slice(0, 6)}${'•'.repeat(24)}${details.value.api_key.slice(-4)}`
})

const curlTemplate = computed(
	() => `curl ${details.value?.gateway_url}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $LLM_API_KEY" \\
  -d '{
    "model": "${modelId.value}",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
)

const copy = async (value: string, label: string): Promise<void> => {
	await navigator.clipboard.writeText(value)
	successToast(`${label} copied.`)
}

const copyCurl = (): void => {
	if (!details.value) return
	void copy(
		curlTemplate.value.replace('$LLM_API_KEY', details.value.api_key),
		'Command',
	)
}

const pendingRevoke = ref<ServiceApiKey | null>(null)
const confirmRevoke = async (): Promise<void> => {
	const key = pendingRevoke.value
	pendingRevoke.value = null
	if (key) await revokeKey(key.name)
}
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl px-6 pb-8 pt-5">
			<div class="flex items-start justify-between gap-4">
				<p class="max-w-prose text-p-sm text-ink-gray-5">
					Central-issued keys for use in your own apps. Usage bills to your
					team, same as on-site AI.
				</p>

				<Button
					v-if="canManage"
					variant="subtle"
					size="sm"
					label="Generate key"
					icon-left="lucide-plus"
					class="shrink-0"
					@click="openGenerate"
				/>
			</div>

			<div
				v-if="apiKeysLoading && !apiKeys.length"
				class="mt-3 flex justify-center py-16"
			>
				<span class="text-p-sm text-ink-gray-5">Loading…</span>
			</div>

			<div
				v-else-if="apiKeys.length"
				class="mt-3 divide-y divide-outline-gray-1 border-t border-outline-gray-1"
			>
				<div
					v-for="key in apiKeys"
					:key="key.name"
					class="flex items-center gap-3 py-2.5"
					:class="key.status === 'Active' && canManage ? 'cursor-pointer' : ''"
				>
					<span
						class="grid size-8 shrink-0 place-items-center rounded-lg bg-surface-gray-2 text-ink-gray-6"
					>
						<lucide-key-round class="size-4" />
					</span>

					<!-- masked key -->
					<div class="min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="truncate text-sm font-medium text-ink-gray-9"
								>{{ key.label }}</span
							>
							<Badge
								:theme="key.status === 'Active' ? 'green' : 'gray'"
								variant="subtle"
								size="sm"
								:label="key.status"
							/>
						</div>
						<div class="mt-0.5 truncate font-mono text-xs text-ink-gray-5">
							{{ key.masked_key }}
						</div>
					</div>

					<div class="shrink-0 text-right">
						<div class="text-p-sm tabular-nums text-ink-gray-8">
							{{ Math.round(key.last_usage_total || 0).toLocaleString() }}
						</div>
						<div class="text-p-xs text-ink-gray-5">tokens</div>
					</div>

					<Dropdown
						v-if="canManage && key.status === 'Active'"
						:options="rowActions(key)"
						placement="right"
					>
						<template #trigger>
							<Button
								variant="ghost"
								icon="lucide-ellipsis-vertical"
								:loading="busyKey === key.name || revealingName === key.name"
								aria-label="API key actions"
								@click.stop
							/>
						</template>
					</Dropdown>
					<span v-else class="w-6 shrink-0" />
				</div>
			</div>

			<EmptyState
				v-else
				class="mt-3"
				icon="lucide-key-round"
				title="No API keys yet"
				description="Generate a key to call our models from your own apps."
			>
				<template v-if="canManage" #action>
					<Button
						variant="subtle"
						size="sm"
						label="Generate key"
						icon-left="lucide-plus"
						@click="openGenerate"
					/>
				</template>
			</EmptyState>
		</div>
	</div>

	<Dialog
		v-model="generateOpen"
		title="Generate API key"
		:actions="[
			{
				label: 'Generate',
				variant: 'solid',
				loading: generating,
				disabled: !newLabel.trim(),
				onClick: generate,
			},
		]"
	>
		<template #default>
			<FormControl
				v-model="newLabel"
				label="Label"
				placeholder="e.g. n8n prod"
				description="A name to recognise this key by. You can revoke it independently."
				@keyup.enter="generate"
			/>
		</template>
	</Dialog>

	<Dialog
		:model-value="!!details"
		:title="details ? `API key - ${details.label}` : ''"
		size="2xl"
		@update:model-value="
			(v: boolean) => {
				if (!v) details = null
			}
		"
	>
		<template #default>
			<div v-if="details" class="space-y-5">
				<p class="text-p-sm text-ink-gray-6">
					Use it from any app, script, or tool. Usage bills to your team just
					like on-site AI.
				</p>

				<div>
					<label class="mb-1 block text-p-sm font-medium text-ink-gray-7">
						Gateway URL
					</label>
					<div class="flex items-center gap-2">
						<code
							class="min-w-0 flex-1 truncate rounded-md border border-outline-gray-2 bg-surface-gray-1 px-3 py-2 font-mono text-sm text-ink-gray-8"
						>
							{{ details.gateway_url }}
						</code>
						<Button
							icon="lucide-copy"
							aria-label="Copy gateway URL"
							@click="copy(details.gateway_url, 'Gateway URL')"
						/>
					</div>
				</div>

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
							:icon="secretRevealed ? 'lucide-eye-off' : 'lucide-eye'"
							:aria-label="secretRevealed ? 'Hide key' : 'Reveal key'"
							@click="secretRevealed = !secretRevealed"
						/>
						<Button
							icon="lucide-copy"
							aria-label="Copy API key"
							@click="copy(details.api_key, 'API key')"
						/>
					</div>
					<p class="mt-2 text-xs text-ink-gray-5">
						Treat it like a password. Revocable on its own.
					</p>
				</div>

				<!-- example codeblock -->
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

				<div
					class="flex border border-outline-gray-2 bg-surface-gray-2 rounded"
				>
					<pre
						class="flex overflow-x-auto rounded-md  p-3 font-mono text-xs leading-relaxed text-ink-gray-8"
					>{{ curlTemplate }}</pre>

					<Button
						icon="lucide-copy"
						size="sm"
						class="sticky top-0 right-0 ml-auto"
						aria-label="Copy command"
						@click="copyCurl"
					/>
				</div>

				<p class="mt-1 text-xs text-ink-gray-5">
					Copy runs with your key filled in; the shown command keeps it as
					<code class="font-mono">$LLM_API_KEY</code>.
				</p>
			</div>
		</template>
	</Dialog>

	<Dialog
		:model-value="!!pendingRevoke"
		title="Revoke API key"
		:message="`Revoke ${pendingRevoke?.label}? Any app using it will stop working immediately. This can't be undone.`"
		:actions="[
			{
				label: 'Revoke',
				variant: 'solid',
				theme: 'red',
				loading: busyKey === pendingRevoke?.name,
				onClick: confirmRevoke,
			},
		]"
		@update:model-value="
			(v: boolean) => {
				if (!v) pendingRevoke = null
			}
		"
	/>
</template>
