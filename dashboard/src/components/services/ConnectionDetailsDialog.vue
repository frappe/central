<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Dialog, Select, Spinner } from 'frappe-ui'
import { useServices } from '@/composables/useServices'
import { successToast, getErrorMessage } from '@/lib/toast'
import type { ServiceModel, SiteCredential } from '@/composables/useServices'

// The bring-your-own surface: reveal a site's gateway URL + key and a ready-to-run
// curl, so the same credential the platform delivers to the site can also drive an
// external app. The key is fetched on open (service:manage), masked until revealed,
// and never rendered inline in the shown curl — the copy button injects it.
const props = defineProps<{
	open: boolean
	managedService: string
	site: string
	models: ServiceModel[]
}>()

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

const { fetchCredential } = useServices()

const loading = ref(false)
const error = ref('')
const credential = ref<SiteCredential | null>(null)
const revealed = ref(false)
const selectedModel = ref('')

const modelOptions = computed(() =>
	props.models.length
		? props.models.map((m) => ({ label: `${m.name} (${m.tier})`, value: m.name }))
		: [{ label: 'MODEL_ID', value: '' }],
)

const modelId = computed(() => selectedModel.value || 'MODEL_ID')

const maskedKey = computed(() => {
	const key = credential.value?.api_key ?? ''
	if (!key) return ''
	return revealed.value ? key : `${key.slice(0, 6)}${'•'.repeat(24)}${key.slice(-4)}`
})

// Shown with a placeholder token so a screenshot never leaks the secret; the copy
// button below swaps in the real key.
const curlTemplate = computed(() => {
	const url = credential.value?.gateway_url ?? 'GATEWAY_URL'
	return `curl ${url}/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer $LLM_API_KEY" \\
  -d '{
    "model": "${modelId.value}",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`
})

watch(
	() => props.open,
	async (isOpen) => {
		if (!isOpen) return
		revealed.value = false
		error.value = ''
		selectedModel.value = props.models[0]?.name ?? ''
		loading.value = true
		try {
			credential.value = await fetchCredential(props.managedService, props.site)
		} catch (e) {
			error.value = getErrorMessage(e)
		} finally {
			loading.value = false
		}
	},
)

async function copy(value: string, label: string): Promise<void> {
	await navigator.clipboard.writeText(value)
	successToast(`${label} copied.`)
}

function copyCurl(): void {
	const key = credential.value?.api_key ?? '$LLM_API_KEY'
	void copy(curlTemplate.value.replace('$LLM_API_KEY', key), 'Command')
}
</script>

<template>
	<Dialog v-model="open" :title="`Connect to ${site}`" size="2xl">
		<template #default>
			<div v-if="loading" class="flex items-center gap-2 py-8 text-ink-gray-5">
				<Spinner class="size-4" />
				<span class="text-p-sm">Loading connection details…</span>
			</div>

			<p v-else-if="error" class="py-6 text-p-sm text-ink-red-3">{{ error }}</p>

			<div v-else-if="credential" class="space-y-5">
				<p class="text-p-sm text-ink-gray-6">
					An OpenAI-compatible endpoint. Use it from any app, script, or tool — usage
					bills to your team just like on-site AI.
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
							{{ credential.gateway_url }}
						</code>
						<Button
							icon="lucide-copy"
							aria-label="Copy gateway URL"
							@click="copy(credential.gateway_url, 'Gateway URL')"
						/>
					</div>
				</div>

				<!-- API key -->
				<div>
					<label class="mb-1 block text-p-sm font-medium text-ink-gray-7">
						API key
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
							@click="copy(credential.api_key, 'API key')"
						/>
					</div>
					<p class="mt-1 text-xs text-ink-gray-5">
						Scoped to this site and revocable on its own. Treat it like a password.
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
							>{{ curlTemplate }}</pre
						>
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
	</Dialog>
</template>
