<script setup lang="ts">
import { Badge, Button, Dialog, FormControl } from 'frappe-ui'
import { computed, h, ref, watch } from 'vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import ApiKeyRowActions from '@/components/services/ApiKeyRowActions.vue'
import ConnectionDetails from '@/components/services/ConnectionDetails.vue'
import type {
	RevealedKey,
	ServiceApiKey,
	ServiceModel,
} from '@/composables/useServices'
import { useServices } from '@/composables/useServices'
import { errorToast } from '@/lib/toast'

// The API Keys tab: keys Central issues from the provider for the customer's own
// apps. Generate → shows the key + curl once; Reveal re-opens it anytime (we store
// it); Revoke kills it at the provider. Usage bills to the team like every key.
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

const query = ref(
	createListViewQuery({
		pageSize: 20,
		sort: { key: 'creation', direction: 'desc' },
	}),
)

const columns = computed<ListViewColumn<ServiceApiKey>[]>(() => [
	{
		accessorKey: 'label',
		header: 'Label',
		meta: { cellClass: 'truncate font-medium' },
	},
	{
		accessorKey: 'status',
		header: 'Status',
		enableSorting: false,
		cell: ({ row }) =>
			h(Badge, {
				theme: row.original.status === 'Active' ? 'green' : 'gray',
				variant: 'subtle',
				label: row.original.status,
			}),
	},
	{
		accessorKey: 'creation',
		header: 'Created',
		cell: ({ row }) => new Date(row.original.creation).toLocaleDateString(),
	},
	{
		accessorKey: 'last_usage_total',
		header: 'Usage (tokens)',
		meta: { align: 'end' },
		cell: ({ row }) =>
			Math.round(row.original.last_usage_total || 0).toLocaleString(),
	},
	{
		id: 'actions',
		header: '',
		enableSorting: false,
		size: 1,
		meta: { align: 'end' },
		cell: ({ row }) => {
			const key = row.original
			if (!props.canManage || key.status !== 'Active') return null
			return h(ApiKeyRowActions, {
				apiKey: key,
				busy: busyKey.value === key.name || revealingName.value === key.name,
				onReveal: reveal,
				onRevoke: (k: ServiceApiKey) => {
					pendingRevoke.value = k
				},
			})
		},
	},
])

// Clicking a row reveals its key (managers only) — the same as the ⋯ Reveal.
function onRowClick(key: ServiceApiKey): void {
	if (props.canManage && key.status === 'Active') reveal(key)
}

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

// Details dialog (after generate, and on reveal) — reuses ConnectionDetails.
const details = ref<RevealedKey | null>(null)
const revealingName = ref('')

async function reveal(key: ServiceApiKey): Promise<void> {
	revealingName.value = key.name
	try {
		details.value = await revealKey(key.name)
	} catch (e) {
		errorToast(e)
	} finally {
		revealingName.value = ''
	}
}

// Revoke confirm
const pendingRevoke = ref<ServiceApiKey | null>(null)
async function confirmRevoke(): Promise<void> {
	const key = pendingRevoke.value
	pendingRevoke.value = null
	if (key) await revokeKey(key.name)
}
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
		<ListView
			class="mx-auto flex h-full max-w-4xl flex-col"
			v-model:query="query"
			:rows="apiKeys"
			:columns="columns"
			:row-key="(key: ServiceApiKey) => key.name"
			:loading="apiKeysLoading"
			searchable
			search-placeholder="Search keys..."
			item-label="key"
			:empty-state="{
				title: 'No API keys yet',
				description: 'Generate a key to call our models from your own apps.',
			}"
			@row-click="onRowClick"
		>
			<template v-if="canManage" #toolbar>
				<Button
					variant="solid"
					label="Generate"
					icon-left="lucide-plus"
					@click="openGenerate"
				/>
			</template>
			<template v-if="canManage" #empty-action>
				<Button
					variant="solid"
					label="Generate Key"
					icon-left="lucide-plus"
					@click="openGenerate"
				/>
			</template>
		</ListView>
	</div>

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
		:title="details ? `API key - ${details.label}` : ''"
		size="2xl"
		@update:model-value="
	(v: boolean) => {
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
