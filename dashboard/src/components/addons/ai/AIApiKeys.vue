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
import { computed, ref, watch } from 'vue'

import AIQuickstart from '@/components/addons/ai/AIQuickstart.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import ListViewPagination from '@/components/common/list-view/ListViewPagination.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime } from '@/lib/datetime'
import { getErrorMessage, reportError } from '@/lib/feedback'
import { compactNumber } from '@/lib/format'
import type { AIApiKey, AIRateLimit } from '@/types/ai'

interface Props {
	canManage: boolean
}

const props = defineProps<Props>()

const {
	ai,
	apiKeys,
	apiKeysLoading,
	apiKeysError,
	busyKey,
	loadApiKeys,
	createApiKey,
	setCaps,
	capsSaving,
	models,
	modelsLoading,
	loadModels,
	revokeApiKey,
} = useAI()

loadApiKeys()

// Every team is prepaid at Grove: the caps show once its spend has loaded.
const prepaid = computed(() => !!ai.value?.spend)
const spend = computed(() => ai.value?.spend)
// When the spend and each key's month figure are from: Grove's last pull. A cap change is
// checked against the live figure at Grove, which refuses and says so if it no longer fits.
const asOf = computed(() =>
	ai.value?.usage?.as_of
		? formatDateTime(ai.value.usage.as_of)
		: 'the last count',
)
const activeKeys = computed(() =>
	apiKeys.value.filter((key) => key.status === 'active'),
)
// A plan with max_keys 0 sets no limit.
const atKeyLimit = computed(
	() =>
		!!spend.value &&
		spend.value.max_keys > 0 &&
		activeKeys.value.length >= spend.value.max_keys,
)
const canSetCaps = computed(
	() => prepaid.value && props.canManage && activeKeys.value.length > 0,
)
const keyCountLabel = computed(() => {
	const live = activeKeys.value.length
	const max = spend.value?.max_keys ?? 0
	if (max > 0) return `${live} of ${max} keys`
	return `${live} ${live === 1 ? 'key' : 'keys'}`
})
// All keys come in one call; search and page them on the client.
const query = ref('')
const visibleKeys = computed(() => {
	const q = query.value.trim().toLowerCase()
	if (!q) return apiKeys.value
	return apiKeys.value.filter((key) => key.title.toLowerCase().includes(q))
})
const PAGE_SIZE = 10
const page = ref(1)
const pageCount = computed(() =>
	Math.ceil(visibleKeys.value.length / PAGE_SIZE),
)
const pagedKeys = computed(() =>
	visibleKeys.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
)
watch(pageCount, (count) => {
	page.value = Math.min(page.value, Math.max(count, 1))
})
watch(query, () => {
	page.value = 1
})
const isCapReached = (key: AIApiKey): boolean =>
	key.cap > 0 && key.month_spent >= key.cap
const capPercent = (key: AIApiKey): number =>
	Math.min(100, (key.month_spent / key.cap) * 100)
// Gray while there is room, amber from 80%, red once the gateway refuses it.
const capBarClass = (key: AIApiKey): string =>
	isCapReached(key)
		? 'bg-surface-red-5'
		: capPercent(key) >= 80
			? 'bg-surface-amber-7'
			: 'bg-surface-gray-10'
const geographies = computed(() => ai.value?.geographies ?? [])
// Only a geography with a gateway can mint a key or be called; one without keeps its label for
// the keys already listed under it.
const mintable = computed(() => geographies.value.filter((g) => g.endpoint))
const geographyLabel = (name: string): string =>
	geographies.value.find((g) => g.name === name)?.label ?? name

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
const limitChips = (limits: AIRateLimit[]) =>
	limits.map((limit) => ({
		key: `${limit.metric}:${limit.window}`,
		label: `${compactNumber(limit.value)} ${METRIC_LETTERS[limit.metric] ?? limit.metric}${WINDOW_LETTERS[limit.window] ?? ''}`,
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
		mintable.value.find((g) => g.is_default)?.name ??
		mintable.value[0]?.name ??
		''
	newCap.value = ''
	createError.value = ''
	createOpen.value = true
}

const geographyOptions = computed(() =>
	mintable.value.map((g) => ({ label: g.label, value: g.name })),
)

const create = async (): Promise<void> => {
	const label = newLabel.value.trim()
	if (!label) return

	creating.value = true
	createError.value = ''
	try {
		await createApiKey({
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

// ── Caps: every live key's in one dialog, saved in one call ──
const capsOpen = ref(false)
const capValues = ref<Record<string, string>>({})
const capsError = ref('')
// What the month would have spoken for with these caps, as Grove checks it: each live key's
// cap or what it spent this month, whichever is more, plus what revoked keys spent.
const committedTotal = computed(() =>
	apiKeys.value.reduce(
		(sum, key) =>
			sum +
			(key.status === 'active'
				? Math.max(Number(capValues.value[key.name]) || 0, key.month_spent)
				: key.month_spent),
		0,
	),
)
// Grove checks only a raise, so a team past a lowered limit may still save lowers.
const capsOverLimit = computed(
	() =>
		committedTotal.value > (spend.value?.spend_limit ?? 0) &&
		committedTotal.value > (spend.value?.committed ?? 0),
)
// A cap is whole US dollars, 0 included; Central refuses anything else.
const isWholeCap = (value: string): boolean =>
	Number.isInteger(Number(value)) && Number(value) >= 0
const capsInvalid = computed(() =>
	activeKeys.value.some((key) => !isWholeCap(capValues.value[key.name])),
)

const openCaps = (): void => {
	capValues.value = Object.fromEntries(
		activeKeys.value.map((key) => [key.name, String(key.cap)]),
	)
	capsError.value = ''
	capsOpen.value = true
}

const saveCaps = async (): Promise<void> => {
	capsError.value = ''
	const changed = Object.fromEntries(
		activeKeys.value
			.filter((key) => Number(capValues.value[key.name]) !== key.cap)
			.map((key) => [key.name, Number(capValues.value[key.name])]),
	)
	try {
		if (Object.keys(changed).length) await setCaps(changed)
		capsOpen.value = false
	} catch (e) {
		capsError.value = getErrorMessage(e)
	}
}

// ── How to call: a geography's gateway and what a key there starts with ──
const helpOpen = ref(false)
const helpGeography = ref('')
const helpGatewayUrl = computed(
	() =>
		geographies.value.find((g) => g.name === helpGeography.value)?.endpoint ??
		'',
)

const openHelp = (): void => {
	helpGeography.value ||=
		mintable.value.find((g) => g.is_default)?.name ??
		mintable.value[0]?.name ??
		''
	helpOpen.value = true
}

watch(helpGeography, async (name) => {
	if (!name) return
	try {
		await loadModels(name)
	} catch (e) {
		reportError(e)
	}
})

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
						and monthly cap: what it may spend each month, refused once reached
						until the next</template
					>.
				</p>

				<div class="flex shrink-0 items-center gap-2">
					<Button
						label="How to call"
						icon-left="lucide-circle-help"
						@click="openHelp"
					/>
					<Tooltip
						v-if="canManage"
						:text="
							atKeyLimit
								? `Your plan allows ${spend?.max_keys} live keys. Revoke one to create another.`
								: ''
						"
					>
						<Button
							class="shrink-0"
							label="Create key"
							icon-left="lucide-plus"
							:disabled="atKeyLimit"
							@click="openCreate"
						/>
					</Tooltip>
				</div>
			</div>
			<Alert
				v-if="spend?.suspended"
				class="mt-4"
				theme="red"
				title="Keys are paused"
				description="An invoice is unpaid. Every key is refused until it is settled."
			/>
			<div
				v-if="apiKeys.length || canSetCaps"
				class="mt-4 flex items-center justify-between gap-4"
			>
				<TextInput
					v-if="apiKeys.length"
					v-model="query"
					class="w-64"
					size="md"
					placeholder="Search keys by title"
					aria-label="Search keys by title"
				>
					<template #prefix>
						<span
							class="lucide-search size-4 text-ink-gray-5"
							aria-hidden="true"
						/>
					</template>
				</TextInput>
				<Button
					v-if="canSetCaps"
					class="ml-auto shrink-0"
					label="Set monthly caps"
					icon-left="lucide-wallet"
					@click="openCaps"
				/>
			</div>

			<p
				v-if="prepaid"
				class="mt-3 text-p-xs text-ink-gray-5"
				aria-live="polite"
			>
				Caps and this month's spend take up
				{{ usd(spend?.committed ?? 0) }}
				of your plan's
				{{ usd(spend?.spend_limit ?? 0) }}
				a month, as of {{ asOf }} · {{ keyCountLabel }}.
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
				v-else-if="visibleKeys.length"
				class="mt-3 divide-y divide-outline-gray-1 border-t border-outline-gray-1"
			>
				<div
					v-for="key in pagedKeys"
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
							<span class="truncate text-sm-medium text-ink-gray-9">
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
							class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-p-sm text-ink-gray-5"
						>
							<span>{{ key.masked }}</span>
							<template v-if="key.status === 'active'">
								<template
									v-for="chip in limitChips(key.limits)"
									:key="chip.key"
								>
									<span aria-hidden="true">·</span>
									<Tooltip :text="chip.text">
										<span class="tabular-nums">{{ chip.label }}</span>
									</Tooltip>
								</template>
							</template>
						</div>
					</div>

					<template v-if="prepaid && key.status === 'active'">
						<Tooltip
							v-if="!key.cap"
							text="Refused until it gets a monthly cap."
						>
							<Badge theme="orange" label="No cap yet" />
						</Tooltip>
						<Tooltip
							v-else
							:text="
								isCapReached(key)
									? 'Cap reached: refused until the month ends or the cap is raised.'
									: `Spent this month of its ${usd(key.cap)} monthly cap.`
							"
						>
							<div class="w-32 shrink-0 text-right">
								<div class="text-xs tabular-nums text-ink-gray-7">
									<span class="font-medium text-ink-gray-9"
										>{{ usd(key.month_spent) }}</span
									>
									/ {{ usd(key.cap) }}
								</div>
								<div
									class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-gray-2"
									role="meter"
									:aria-valuenow="key.month_spent"
									:aria-valuemax="key.cap"
									:aria-label="`${key.title}: spent this month of its cap`"
								>
									<span
										class="block h-full rounded-full"
										:class="capBarClass(key)"
										:style="{ width: `${capPercent(key)}%` }"
									/>
								</div>
							</div>
						</Tooltip>
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
				v-else-if="apiKeys.length"
				class="mt-3"
				icon="lucide-search"
				title="No keys match"
				description="No key is named that. Try another name, or clear the search."
			/>

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

			<ListViewPagination
				v-if="pageCount > 1"
				:page="page"
				:page-count="pageCount"
				:page-size="PAGE_SIZE"
				:can-previous="page > 1"
				:can-next="page < pageCount"
				:show-page-size="false"
				:count-text="`${visibleKeys.length} keys`"
				@first="page = 1"
				@previous="page--"
				@next="page++"
				@last="page = pageCount"
			/>
		</div>
	</div>

	<Dialog v-model="helpOpen" title="How to call the models" size="2xl">
		<template #default>
			<div class="space-y-4">
				<div class="flex items-start justify-between gap-4">
					<p class="text-p-sm text-ink-gray-6">
						A key works in its own geography, on both surfaces: point the OpenAI
						or the Anthropic SDK at that geography's base URL and use it as you
						would with the vendor.
					</p>
					<Select
						v-if="geographyOptions.length > 1"
						v-model="helpGeography"
						class="w-fit shrink-0"
						:options="geographyOptions"
						aria-label="Geography"
					>
						<template #prefix>
							<span class="text-ink-gray-5">Geography</span>
						</template>
					</Select>
				</div>
				<div v-if="modelsLoading" class="flex justify-center py-8">
					<Spinner class="size-5 text-ink-gray-5" />
				</div>
				<AIQuickstart v-else :gateway-url="helpGatewayUrl" :models="models" />
			</div>
		</template>
	</Dialog>

	<Dialog v-model="createOpen" title="Create API key">
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
					step="1"
					label="Cap (USD)"
					placeholder="0"
					description="What this key may spend each month. Leave it at 0 to set it later: the key is refused until it has a cap."
					@keyup.enter="create"
				/>
			</div>
			<p v-if="createError" class="mt-2 text-p-sm text-ink-red-6">
				{{ createError }}
			</p>
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-3">
				<p v-if="prepaid" class="mr-auto text-p-sm text-ink-gray-5">
					Caps and this month's spend take up
					{{ usd(spend?.committed ?? 0) }}
					of your plan's
					{{ usd(spend?.spend_limit ?? 0) }}
					a month, as of {{ asOf }}.
				</p>
				<Button
					variant="solid"
					label="Create"
					:loading="creating"
					:disabled="!newLabel.trim() || !newGeography || !isWholeCap(newCap)"
					@click="create"
				/>
			</div>
		</template>
	</Dialog>

	<Dialog v-model="capsOpen" title="Set caps" size="2xl">
		<template #default>
			<Alert v-if="capsError" class="mb-4" theme="red" :title="capsError" />
			<div
				class="mb-2 grid grid-cols-[2fr_1fr_1fr_1fr] gap-3 text-sm-medium text-ink-gray-6"
				aria-hidden="true"
			>
				<span class="min-w-0">Key</span>
				<span class="text-center">Geography</span>
				<span class="text-center">Spent this month</span>
				<span>Cap (USD)</span>
			</div>
			<div class="space-y-3">
				<div
					v-for="(key, index) in activeKeys"
					:key="key.name"
					class="grid grid-cols-[2fr_1fr_1fr_1fr] items-center gap-3"
				>
					<div class="min-w-0 truncate text-base text-ink-gray-8">
						{{ key.title }}
					</div>
					<span class="min-w-0 truncate text-center text-base text-ink-gray-7">
						{{ geographyLabel(key.geography) }}
					</span>
					<span class="text-center text-base tabular-nums text-ink-gray-7">
						{{ usd(key.month_spent) }}
					</span>
					<TextInput
						v-model="capValues[key.name]"
						type="number"
						min="0"
						step="1"
						placeholder="0"
						:autofocus="index === 0"
						:aria-label="`Monthly cap for ${key.title} (USD)`"
						:disabled="capsSaving"
						@keyup.enter="saveCaps"
					/>
				</div>
			</div>
			<p class="mt-4 text-p-sm text-ink-gray-5">
				A key at 0 is refused until it gets a cap. Spend is as of {{ asOf }}:
				The live figure is checked when you save.
			</p>
		</template>
		<template #actions>
			<div class="flex items-center justify-between gap-3">
				<p
					class="max-w-sm text-p-sm"
					:class="capsOverLimit ? 'text-ink-red-6' : 'text-ink-gray-5'"
					aria-live="polite"
				>
					{{ usd(committedTotal) }}
					of your plan's
					{{ usd(spend?.spend_limit ?? 0) }}
					a month, caps and this month's spend together, as of {{ asOf }}
				</p>
				<div class="flex items-center gap-2">
					<Button
						label="Cancel"
						:disabled="capsSaving"
						@click="capsOpen = false"
					/>
					<Button
						variant="solid"
						label="Save caps"
						:loading="capsSaving"
						:disabled="capsInvalid || capsOverLimit"
						@click="saveCaps"
					/>
				</div>
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
					and its cap frees room for another key</template
				>. This can't be undone.
			</p>
		</template>
	</ConfirmDialog>
</template>
