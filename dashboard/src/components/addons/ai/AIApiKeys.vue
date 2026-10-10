<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Dialog,
	type DropdownOptions,
	dayjs,
	Switch,
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
import type { AIApiKey, AIModel, MintedKey } from '@/types/ai'

interface Props {
	models: AIModel[]
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
	setBalanceAccess,
	revokeApiKey,
} = useAI()

loadApiKeys()

const setBalance = async (key: AIApiKey, allowed: boolean): Promise<void> => {
	try {
		await setBalanceAccess(key.name, allowed)
	} catch (e) {
		reportError(e)
	}
}

// Grove refuses to revoke a key before `revocable_at`; the dialog says so and asks nothing.
const isRevocable = (key: AIApiKey): boolean =>
	new Date(key.revocable_at) <= new Date()
const revocableFrom = (key: AIApiKey): string =>
	dayjs(key.revocable_at).format('MMM D, h:mm A')

const rowActions = (key: AIApiKey): DropdownOptions => [
	{
		label: 'Revoke',
		icon: 'lucide-trash-2',
		theme: 'red',
		onClick: () => (revokeTarget.value = key),
	},
]

// ── Create ──
const createOpen = ref(false)
const newLabel = ref('')
const creating = ref(false)
const createError = ref('')

const openCreate = (): void => {
	newLabel.value = ''
	createError.value = ''
	createOpen.value = true
}

const create = async (): Promise<void> => {
	const label = newLabel.value.trim()
	if (!label) return

	creating.value = true
	createError.value = ''
	try {
		minted.value = await createApiKey(label)
		createOpen.value = false
	} catch (e) {
		createError.value = getErrorMessage(e)
	} finally {
		creating.value = false
	}
}

// The one time the secret is shown.
const minted = ref<MintedKey | null>(null)

// The same examples with $API_KEY in place of a secret, for any key made earlier.
const helpOpen = ref(false)
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
const limitChips = computed(() =>
	(ai.value?.rate_limits ?? []).map((limit) => ({
		key: `${limit.metric}:${limit.window}`,
		label: `${compact.format(limit.value)} ${METRIC_LETTERS[limit.metric] ?? limit.metric}${WINDOW_LETTERS[limit.window] ?? ''}`,
		text: `${limit.value.toLocaleString()} ${METRIC_WORDS[limit.metric] ?? limit.metric} ${WINDOW_WORDS[limit.window] ?? limit.window}`,
	})),
)

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
					is created. A key that reads balance can fetch the team's remaining
					credit from the gateway; the first key starts with that on.
				</p>

				<div class="flex shrink-0 items-center gap-2">
					<Button
						v-if="ai?.gateway_url"
						variant="ghost"
						icon="lucide-circle-help"
						label="How to call the models"
						tooltip="How to call the models"
						@click="helpOpen = true"
					/>
					<Button
						v-if="canManage"
						label="Create key"
						icon-left="lucide-plus"
						@click="openCreate"
					/>
				</div>
			</div>

			<div
				v-if="limitChips.length"
				class="mt-3 flex flex-wrap items-center justify-end gap-2"
			>
				<span class="text-p-xs text-ink-gray-5">
					Rate limits, shared by every key of the team
				</span>
				<Tooltip v-for="chip in limitChips" :key="chip.key" :text="chip.text">
					<Badge :label="chip.label" theme="gray" size="md" class="font-mono" />
				</Tooltip>
			</div>

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
						<div class="flex items-center gap-2">
							<span class="truncate text-sm font-medium text-ink-gray-9">
								{{ key.title }}
							</span>
							<Badge
								:theme="key.status === 'active' ? 'green' : 'gray'"
								size="sm"
								:label="key.status === 'active' ? 'Active' : 'Revoked'"
							/>
						</div>
						<div class="mt-0.5 truncate font-mono text-xs text-ink-gray-5">
							{{ key.masked }}
						</div>
					</div>

					<template v-if="key.status === 'active'">
						<Switch
							v-if="canManage"
							:model-value="!!key.can_read_balance"
							label="Reads balance"
							:disabled="busyKey === key.name"
							@update:model-value="(allowed: boolean) => setBalance(key, allowed)"
						/>
						<span
							v-else-if="key.can_read_balance"
							class="text-p-xs text-ink-gray-5"
						>
							Reads balance
						</span>
					</template>

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

	<Dialog v-model="helpOpen" title="Calling the models" size="2xl">
		<template #default>
			<div class="space-y-4">
				<p class="text-p-sm text-ink-gray-6">
					One key works on both surfaces: point the OpenAI or the Anthropic SDK
					at the base URL below and use it as you would with the vendor.
				</p>
				<AIQuickstart
					v-if="ai?.gateway_url"
					:gateway-url="ai.gateway_url"
					:models="models"
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
				disabled: !newLabel.trim(),
				onClick: create,
			},
		]"
	>
		<template #default>
			<TextInput
				v-model="newLabel"
				label="Label"
				placeholder="e.g. n8n prod"
				description="A name to recognise this key by. New keys can take a few minutes to start working."
				@keyup.enter="create"
			/>
			<p v-if="createError" class="mt-2 text-p-sm text-ink-red-6">
				{{ createError }}
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

				<!-- The examples carry the key, so what is copied runs as is. -->
				<AIQuickstart
					:gateway-url="minted.gateway_url"
					:models="models"
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
				>? Any app using it stops working within a few minutes. This can't be
				undone.
			</p>
		</template>
	</ConfirmDialog>
</template>
