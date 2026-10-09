<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Dialog,
	type DropdownOptions,
	dayjs,
	Select,
	Spinner,
	TextInput,
	Tooltip,
} from 'frappe-ui'
import { computed, ref } from 'vue'

import AIQuickstart from '@/components/addons/ai/AIQuickstart.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import { useAI } from '@/composables/useAI'
import { getErrorMessage, reportError } from '@/lib/feedback'
import type { AIApiKey, AIRateLimit, MintedKey } from '@/types/ai'

interface Props {
	canManage: boolean
}

defineProps<Props>()

const {
	ai,
	apiKeys,
	apiKeysLoading,
	apiKeysError,
	busyKey,
	loadApiKeys,
	createApiKey,
	setCap,
	keyModels,
	keyModelsLoading,
	loadKeyModels,
	revokeApiKey,
} = useAI()

loadApiKeys()

// A free team is never charged: caps mean nothing to it, so they stay off the page.
const prepaid = computed(
	() => !!ai.value?.balance && !ai.value.balance.is_free_user,
)
const unallocated = computed(() => ai.value?.balance?.unallocated ?? 0)
const geographies = computed(() => ai.value?.geographies ?? [])
const geographyLabel = (name: string): string =>
	geographies.value.find((g) => g.name === name)?.label ?? name

// Grove refuses to revoke a key before `revocable_at`; the dialog says so and asks nothing.
const isRevocable = (key: AIApiKey): boolean =>
	new Date(key.revocable_at) <= new Date()
const revocableFrom = (key: AIApiKey): string =>
	dayjs(key.revocable_at).format('MMM D, h:mm A')

const rowActions = (key: AIApiKey): DropdownOptions => [
	...(prepaid.value
		? [
				{
					label: 'Set spend limit',
					icon: 'lucide-wallet',
					onClick: () => openCap(key),
				},
			]
		: []),
	{
		label: 'Revoke',
		icon: 'lucide-trash-2',
		theme: 'red',
		onClick: () => (revokeTarget.value = key),
	},
]

// Grove's limits as the abbreviations a 429 uses: 20 RPM, 100K TPM, 1M TPD.
const METRIC_LETTERS: Record<string, string> = {
	requests: 'R',
	total_tokens: 'T',
}
const WINDOW_LETTERS: Record<string, string> = {
	'1m': 'PM',
	'1h': 'PH',
	'1d': 'PD',
	'1M': 'PMo',
}
const METRIC_WORDS: Record<string, string> = {
	requests: 'requests',
	total_tokens: 'tokens',
}
const WINDOW_WORDS: Record<string, string> = {
	'1m': 'per minute',
	'1h': 'per hour',
	'1d': 'per day',
	'1M': 'per month',
}
const compact = new Intl.NumberFormat(undefined, {
	notation: 'compact',
	maximumFractionDigits: 1,
})
const limitChips = (limits: AIRateLimit[]) =>
	limits.map((limit) => ({
		key: `${limit.metric}:${limit.window}`,
		label: `${compact.format(limit.value)} ${METRIC_LETTERS[limit.metric] ?? limit.metric}${WINDOW_LETTERS[limit.window] ?? ''}`,
		text: `${limit.value.toLocaleString()} ${METRIC_WORDS[limit.metric] ?? limit.metric} ${WINDOW_WORDS[limit.window] ?? limit.window}`,
	}))

const usd = (value: number): string =>
	value.toLocaleString(undefined, {
		style: 'currency',
		currency: 'USD',
		maximumFractionDigits: 2,
	})

// ── Create ──
const createOpen = ref(false)
const newLabel = ref('')
const newGeography = ref('')
const newCap = ref('')
const creating = ref(false)
const createError = ref('')

const openCreate = (): void => {
	newLabel.value = ''
	newGeography.value =
		geographies.value.find((g) => g.is_default)?.name ??
		geographies.value[0]?.name ??
		''
	newCap.value = ''
	createError.value = ''
	createOpen.value = true
}

const geographyOptions = computed(() =>
	geographies.value.map((g) => ({ label: g.label, value: g.name })),
)

const create = async (): Promise<void> => {
	const label = newLabel.value.trim()
	if (!label) return

	creating.value = true
	createError.value = ''
	try {
		minted.value = await createApiKey({
			label,
			geography: newGeography.value,
			...(prepaid.value && newCap.value !== ''
				? { cap: Number(newCap.value) }
				: {}),
		})
		createOpen.value = false
	} catch (e) {
		createError.value = getErrorMessage(e)
	} finally {
		creating.value = false
	}
}

// The one time the secret is shown.
const minted = ref<MintedKey | null>(null)

// ── Cap ──
const capTarget = ref<AIApiKey | null>(null)
const capValue = ref('')
const capError = ref('')

const openCap = (key: AIApiKey): void => {
	capTarget.value = key
	capValue.value = String(key.cap)
	capError.value = ''
}

const saveCap = async (): Promise<void> => {
	if (!capTarget.value) return
	capError.value = ''
	try {
		await setCap(capTarget.value.name, Number(capValue.value))
		capTarget.value = null
	} catch (e) {
		capError.value = getErrorMessage(e)
	}
}

// ── How to call: the key's own gateway and the models it reaches ──
const helpTarget = ref<AIApiKey | null>(null)

const openHelp = async (key: AIApiKey): Promise<void> => {
	helpTarget.value = key
	try {
		await loadKeyModels(key.name)
	} catch (e) {
		reportError(e)
	}
}

// ── Revoke ──
const revokeTarget = ref<AIApiKey | null>(null)
const revokeError = ref('')

const revoke = async (key: AIApiKey): Promise<void> => {
	if (!isRevocable(key)) return
	revokeError.value = ''
	try {
		await revokeApiKey(key.name)
		revokeTarget.value = null
	} catch (e) {
		revokeError.value = getErrorMessage(e)
	}
}
</script>

<template>
	<div class="min-h-0 flex-1 overflow-y-auto">
		<div class="mx-auto w-full max-w-3xl px-6 pb-8 pt-5">
			<div class="flex items-start justify-between gap-4">
				<p class="max-w-prose text-p-sm text-ink-gray-5">
					Keys for use in your own apps. A key's secret is shown once, when it
					is created. Each key works in one geography and has its own rate
					limits<template v-if="prepaid">
						and spend limit: the part of the balance it may spend</template
					>.
				</p>

				<Button
					v-if="canManage"
					class="shrink-0"
					label="Create key"
					icon-left="lucide-plus"
					@click="openCreate"
				/>
			</div>
			<br />
			<p
				v-if="prepaid"
				class="mt-2 text-p-xs text-ink-gray-5"
				aria-live="polite"
			>
				{{ usd(unallocated) }}
				of the balance is not yet handed to any key's spend limit.
			</p>

			<div
				v-if="apiKeysLoading && !apiKeys.length"
				class="mt-3 flex justify-center py-16"
			>
				<span class="text-p-sm text-ink-gray-5">Loading…</span>
			</div>

			<EmptyState
				v-else-if="apiKeysError && !apiKeys.length"
				class="mt-3"
				icon="lucide-cloud-off"
				title="Keys couldn't load"
				:description="getErrorMessage(apiKeysError, 'Try again in a moment.')"
			>
				<template #action>
					<Button label="Retry" @click="loadApiKeys" />
				</template>
			</EmptyState>

			<div
				v-else-if="apiKeys.length"
				class="mt-3 divide-y divide-outline-gray-1 border-t border-outline-gray-1"
			>
				<div
					v-for="key in apiKeys"
					:key="key.name"
					class="flex items-center gap-3 py-2.5"
				>
					<span
						class="grid size-8 shrink-0 place-items-center rounded-6 bg-surface-gray-2 text-ink-gray-6"
					>
						<lucide-key-round class="size-4" />
					</span>

					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<span class="truncate text-sm font-medium text-ink-gray-9">
								{{ key.title }}
							</span>
							<Badge
								:theme="key.status === 'active' ? 'green' : 'gray'"
								size="sm"
								:label="key.status === 'active' ? 'Active' : 'Revoked'"
							/>
							<Tooltip :text="key.gateway_url">
								<Badge
									size="sm"
									theme="blue"
									:label="geographyLabel(key.geography)"
								/>
							</Tooltip>
						</div>
						<div
							class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-gray-5"
						>
							<span class="truncate font-mono">{{ key.masked }}</span>
							<Tooltip
								v-if="prepaid && !key.cap"
								text="Refused until it gets a spend limit. A top-up passes it by until then."
							>
								<Badge size="sm" theme="orange" label="No spend limit yet" />
							</Tooltip>
							<span v-else-if="prepaid">
								{{ usd(key.spent) }}
								of {{ usd(key.cap) }} spend limit
							</span>
							<Tooltip
								v-for="chip in limitChips(key.limits)"
								:key="chip.key"
								:text="chip.text"
							>
								<Badge
									:label="chip.label"
									theme="gray"
									size="sm"
									class="font-mono"
								/>
							</Tooltip>
						</div>
					</div>

					<Button
						v-if="key.status === 'active'"
						variant="ghost"
						icon="lucide-circle-help"
						label="How to call the models"
						tooltip="How to call the models with this key"
						@click="openHelp(key)"
					/>

					<RowActionsMenu
						v-if="canManage && key.status === 'active'"
						:options="rowActions(key)"
						label="API key actions"
						:busy="busyKey === key.name"
					/>
					<span v-else class="w-6 shrink-0" />
				</div>
			</div>

			<EmptyState
				v-else
				class="mt-3"
				icon="lucide-key-round"
				title="No API keys yet"
				description="Create a key to call our models from your own apps."
			>
				<template v-if="canManage" #action>
					<Button
						label="Create key"
						icon-left="lucide-plus"
						@click="openCreate"
					/>
				</template>
			</EmptyState>
		</div>
	</div>

	<Dialog
		:model-value="!!helpTarget"
		:title="helpTarget ? `Calling the models - ${helpTarget.title}` : ''"
		size="2xl"
		@update:model-value="(open: boolean) => !open && (helpTarget = null)"
	>
		<template #default>
			<div v-if="helpTarget" class="space-y-4">
				<p class="text-p-sm text-ink-gray-6">
					One key works on both surfaces: point the OpenAI or the Anthropic SDK
					at the base URL below and use it as you would with the vendor. The
					models are what this key may call in
					{{ geographyLabel(helpTarget.geography) }}.
				</p>
				<div v-if="keyModelsLoading" class="flex justify-center py-8">
					<Spinner class="size-5 text-ink-gray-5" />
				</div>
				<AIQuickstart
					v-else
					:gateway-url="helpTarget.gateway_url"
					:models="keyModels"
				/>
			</div>
		</template>
	</Dialog>

	<Dialog
		v-model="createOpen"
		title="Create API key"
		:actions="[
			{
				label: 'Create',
				variant: 'solid',
				loading: creating,
				disabled: !newLabel.trim() || !newGeography,
				onClick: create,
			},
		]"
	>
		<template #default>
			<div class="space-y-4">
				<TextInput
					v-model="newLabel"
					label="Label"
					placeholder="e.g. n8n prod"
					description="A name to recognise this key by. New keys can take a few minutes to start working."
					@keyup.enter="create"
				/>
				<Select
					v-model="newGeography"
					label="Geography"
					:options="geographyOptions"
					description="Where the key's requests are served. It cannot be changed later: create another key for another geography."
				/>
				<TextInput
					v-if="prepaid"
					v-model="newCap"
					type="number"
					min="0"
					step="0.01"
					label="Spend limit (USD)"
					placeholder="0"
					:description="`What this key may spend. Leave it at 0 to set it later: the key is refused until it has a limit. ${usd(unallocated)} of the balance is not yet handed to any key.`"
					@keyup.enter="create"
				/>
			</div>
			<p v-if="createError" class="mt-2 text-p-sm text-ink-red-6">
				{{ createError }}
			</p>
		</template>
	</Dialog>

	<Dialog
		:model-value="!!capTarget"
		:title="capTarget ? `Spend limit - ${capTarget.title}` : ''"
		:actions="[
			{
				label: 'Save',
				variant: 'solid',
				loading: busyKey === capTarget?.name,
				disabled: !(Number(capValue) > 0),
				onClick: saveCap,
			},
		]"
		@update:model-value="(open: boolean) => !open && (capTarget = null)"
	>
		<template #default>
			<TextInput
				v-model="capValue"
				type="number"
				min="0"
				step="0.01"
				label="Spend limit (USD)"
				:description="`What this key may spend in total; it has spent ${usd(capTarget?.spent ?? 0)}.`"
				@keyup.enter="saveCap"
			/>
			<p class="mt-1 text-p-sm text-ink-gray-5">
				{{ usd(unallocated) }}
				of the balance is free to hand out.
			</p>
			<p v-if="capError" class="mt-2 text-p-sm text-ink-red-6">
				{{ capError }}
			</p>
		</template>
	</Dialog>

	<Dialog
		:model-value="!!minted"
		:title="minted ? `API key - ${minted.label}` : ''"
		size="2xl"
		@update:model-value="(open: boolean) => !open && (minted = null)"
	>
		<template #default>
			<div v-if="minted" class="space-y-5">
				<Alert
					theme="amber"
					title="The key is shown only now"
					description="Copy it somewhere safe. If you lose it, revoke it and create another."
				/>

				<div>
					<label class="mb-1 block text-p-sm font-medium text-ink-gray-7">
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

	<ConfirmDialog
		v-model:target="revokeTarget"
		title="Revoke API key"
		confirm-label="Revoke"
		theme="red"
		:loading="busyKey === revokeTarget?.name"
		:disabled="!!revokeTarget && !isRevocable(revokeTarget)"
		:error="revokeError"
		@confirm="revoke"
		@after-leave="revokeError = ''"
	>
		<template v-if="revokeTarget">
			<p v-if="!isRevocable(revokeTarget)" class="text-p-base text-ink-gray-7">
				<span class="text-base-semibold text-ink-gray-9"
					>{{ revokeTarget.title }}</span
				>
				can be revoked from {{ revocableFrom(revokeTarget) }}, six hours after
				it was created.
			</p>
			<p v-else class="text-p-base text-ink-gray-7">
				Revoke
				<span class="text-base-semibold text-ink-gray-9"
					>{{ revokeTarget.title }}</span
				>? Any app using it stops working within a few minutes<template
					v-if="prepaid"
				>
					and its unspent limit returns to the balance</template
				>. This can't be undone.
			</p>
		</template>
	</ConfirmDialog>
</template>
