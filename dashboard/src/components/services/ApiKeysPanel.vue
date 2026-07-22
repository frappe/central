<script setup lang="ts">
import { ref, watch } from 'vue'
import { Badge, Button, Dialog, FormControl, Spinner } from 'frappe-ui'
import ConnectionDetails from '@/components/services/ConnectionDetails.vue'
import { useServices } from '@/composables/useServices'
import { errorToast } from '@/lib/toast'
import type { RevealedKey, ServiceApiKey, ServiceModel } from '@/composables/useServices'

// The API-keys surface: keys Central issues from the provider for use in the
// customer's own apps. Generate → shows the key + curl once; Reveal re-opens it
// anytime (we store it); Revoke kills it at the provider. Usage bills to the team
// like every other key.
const props = defineProps<{
	managedService: string
	models: ServiceModel[]
	canManage: boolean
}>()

const { apiKeys, apiKeysLoading, busyKey, loadApiKeys, generateApiKey, revealKey, revokeKey } =
	useServices()

watch(
	() => props.managedService,
	(managed) => {
		if (managed) loadApiKeys(managed)
	},
	{ immediate: true },
)

// Generate dialog
const generateOpen = ref(false)
const newLabel = ref('')
const generating = ref(false)

function openGenerate(): void {
	newLabel.value = ''
	generateOpen.value = true
}

async function generate(): Promise<void> {
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

// Details dialog (shown after generate, and on reveal) — reuses ConnectionDetails.
const details = ref<RevealedKey | null>(null)
const revealingName = ref('')

async function reveal(row: ServiceApiKey): Promise<void> {
	revealingName.value = row.name
	try {
		details.value = await revealKey(row.name)
	} catch (e) {
		errorToast(e)
	} finally {
		revealingName.value = ''
	}
}

// Revoke confirm
const pendingRevoke = ref<ServiceApiKey | null>(null)
async function confirmRevoke(): Promise<void> {
	const row = pendingRevoke.value
	pendingRevoke.value = null
	if (row) await revokeKey(row.name)
}
</script>

<template>
	<section class="rounded-lg border border-outline-gray-2 bg-surface-elevation-1 p-5">
		<div class="flex items-start justify-between gap-3">
			<div>
				<h2 class="text-base font-semibold text-ink-gray-9">API keys</h2>
				<p class="mt-1 text-p-sm text-ink-gray-5">
					Keys for calling our models from your own apps, scripts, or tools.
				</p>
			</div>
			<Button
				v-if="canManage"
				variant="solid"
				label="Generate key"
				icon-left="lucide-plus"
				@click="openGenerate"
			/>
		</div>

		<div v-if="apiKeysLoading && !apiKeys.length" class="flex justify-center py-6">
			<Spinner class="size-4 text-ink-gray-4" />
		</div>

		<p v-else-if="!apiKeys.length" class="mt-4 py-6 text-center text-p-sm text-ink-gray-5">
			No API keys yet. Generate one to use our models from your own apps.
		</p>

		<ul v-else class="mt-4 divide-y divide-outline-gray-1">
			<li v-for="key in apiKeys" :key="key.name" class="flex items-center gap-3 py-3">
				<div class="min-w-0 flex-1">
					<div class="flex items-center gap-2">
						<p class="truncate text-sm font-medium text-ink-gray-8">
							{{ key.label }}
						</p>
						<Badge
							v-if="key.status !== 'Active'"
							:label="key.status"
							theme="gray"
							variant="subtle"
							size="sm"
						/>
					</div>
					<p class="truncate text-xs text-ink-gray-5">
						Created {{ new Date(key.creation).toLocaleDateString() }}
					</p>
				</div>

				<template v-if="canManage && key.status === 'Active'">
					<Button
						label="Reveal"
						icon-left="lucide-eye"
						variant="subtle"
						:loading="revealingName === key.name"
						@click="reveal(key)"
					/>
					<Button
						label="Revoke"
						theme="red"
						variant="ghost"
						:loading="busyKey === key.name"
						@click="pendingRevoke = key"
					/>
				</template>
			</li>
		</ul>
	</section>

	<!-- Generate: name the key -->
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

	<!-- Details: the key + curl, on generate and on reveal -->
	<Dialog
		:model-value="!!details"
		:title="details ? `API key — ${details.label}` : ''"
		size="2xl"
		@update:model-value="
			(v) => {
				if (!v) details = null
			}
		"
	>
		<template #default>
			<ConnectionDetails
				v-if="details"
				:gateway-url="details.gateway_url"
				:api-key="details.api_key"
				:models="models"
			/>
		</template>
	</Dialog>

	<!-- Revoke confirm -->
	<Dialog
		:model-value="!!pendingRevoke"
		:title="'Revoke API key'"
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
			(v) => {
				if (!v) pendingRevoke = null
			}
		"
	/>
</template>
