<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Dialog,
	type DropdownOptions,
	dayjs,
	LoadingText,
	Select,
	Spinner,
	TextInput,
	Tooltip,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import ListViewPagination from '@/components/common/list-view/ListViewPagination.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Quickstart from '@/components/services/llm/Quickstart.vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import { getErrorMessage, reportError } from '@/lib/feedback'
import { compactNumber } from '@/lib/format'
import type { AIApiKey, AIRateLimit } from '@/types/ai'

interface Props {
	canManage: boolean
	active: boolean
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
	modelsGeography,
	loadModels,
	revokeApiKey,
} = useAI()

loadApiKeys()

const prepaid = computed(() => !!ai.value?.spend)
const spend = computed(() => ai.value?.spend)
const asOf = computed(() =>
	ai.value?.usage?.as_of
		? formatDateTime(ai.value.usage.as_of)
		: 'the last count',
)
const activeKeys = computed(() =>
	apiKeys.value.filter((key) => key.status === 'active'),
)
const atKeyLimit = computed(
	() =>
		!!spend.value &&
		spend.value.max_keys > 0 &&
		activeKeys.value.length >= spend.value.max_keys,
)
const canSetCaps = computed(
	() => prepaid.value && props.canManage && activeKeys.value.length > 0,
)
const query = ref('')

const searchable = computed(() => apiKeys.value.length > 6)

const sortedKeys = computed(() =>
	[...apiKeys.value].sort(
		(a, b) => Number(a.status === 'revoked') - Number(b.status === 'revoked'),
	),
)

const visibleKeys = computed(() => {
	const search = query.value.trim().toLowerCase()

	if (!search) return sortedKeys.value

	return sortedKeys.value.filter((key) =>
		key.title.toLowerCase().includes(search),
	)
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
const capBarClass = (key: AIApiKey): string =>
	isCapReached(key)
		? 'bg-surface-red-5'
		: capPercent(key) >= 80
			? 'bg-surface-amber-7'
			: 'bg-surface-gray-10'
const geographies = computed(() => ai.value?.geographies ?? [])
const mintable = computed(() => geographies.value.filter((g) => g.endpoint))
const geographyLabel = (name: string): string =>
	geographies.value.find((g) => g.name === name)?.label ?? name

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

const sharedLimits = computed(() => {
	const [first, ...rest] = activeKeys.value.map((key) =>
		JSON.stringify(key.limits),
	)
	if (!first || rest.some((limits) => limits !== first)) return null
	return limitChips(activeKeys.value[0].limits)
})

const usd = (value: number): string =>
	value.toLocaleString(undefined, {
		style: 'currency',
		currency: 'USD',
		maximumFractionDigits: 2,
	})

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

const capsOpen = ref(false)
const capValues = ref<Record<string, string>>({})
const capsError = ref('')
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
const capsOverLimit = computed(
	() =>
		committedTotal.value > (spend.value?.spend_limit ?? 0) &&
		committedTotal.value > (spend.value?.committed ?? 0),
)
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

const helpOpen = ref(false)
const helpGeography = computed({
	get: () => modelsGeography.value,
	set: (name: string) => loadModels(name).catch(reportError),
})
const helpGatewayUrl = computed(
	() =>
		geographies.value.find((g) => g.name === helpGeography.value)?.endpoint ??
		'',
)

const openHelp = (): void => {
	if (!mintable.value.some((g) => g.name === helpGeography.value))
		helpGeography.value =
			mintable.value.find((g) => g.is_default)?.name ??
			mintable.value[0]?.name ??
			''
	helpOpen.value = true
}

defineExpose({ openCreate, openHelp, atKeyLimit })

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
	<section>
		<Teleport v-if="active" defer to="#ai-tab-controls">
			<div class="flex items-center gap-3">
				<TextInput
					v-if="searchable"
					v-model="query"
					class="w-56"
					placeholder="Search keys"
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
					label="Set caps"
					icon-left="lucide-wallet"
					@click="openCaps"
				/>
			</div>
		</Teleport>

		<Alert
			v-if="spend?.suspended"
			class="mb-4"
			theme="red"
			title="Keys are paused"
			description="An invoice is unpaid. Every key is refused until it is settled."
		/>

		<LoadingText v-if="apiKeysLoading && !apiKeys.length" :lines="3" />

		<div
			v-else-if="apiKeysError && !apiKeys.length"
			class="flex items-center justify-between gap-3 rounded-5 border border-outline-gray-1 px-4 py-3"
		>
			<p class="text-p-sm text-ink-gray-6">
				{{ getErrorMessage(apiKeysError, "Couldn't load your keys.") }}
			</p>
			<Button label="Retry" @click="loadApiKeys" />
		</div>

		<div
			v-else-if="!apiKeys.length"
			class="flex flex-wrap items-center justify-between gap-3 rounded-5 border border-dashed border-outline-gray-2 px-4 py-3"
		>
			<p class="text-p-sm text-ink-gray-6">
				No keys yet. Create one to call the models from your own apps.
			</p>
			<Button
				v-if="canManage"
				label="Create key"
				icon-left="lucide-plus"
				@click="openCreate"
			/>
		</div>

		<p
			v-else-if="!visibleKeys.length"
			class="rounded-5 border border-dashed border-outline-gray-2 px-4 py-3 text-p-sm text-ink-gray-6"
		>
			No key is named that. Try another name, or clear the search.
		</p>

		<table v-else class="w-full border-separate border-spacing-0 text-left">
			<thead>
				<tr class="text-sm text-ink-gray-5">
					<th scope="col" class="pb-2 font-normal">Name</th>
					<th scope="col" class="hidden pb-2 font-normal sm:table-cell">
						Geography
					</th>
					<th
						v-if="!sharedLimits"
						scope="col"
						class="hidden pb-2 font-normal lg:table-cell"
					>
						Rate limits
					</th>
					<th scope="col" class="hidden pb-2 font-normal md:table-cell">
						Created
					</th>
					<th v-if="prepaid" scope="col" class="w-36 pb-2 font-normal">
						This month
					</th>
					<th scope="col" class="w-10 pb-2">
						<span class="sr-only">Actions</span>
					</th>
				</tr>
			</thead>

			<tbody>
				<tr
					v-for="key in pagedKeys"
					:key="key.name"
					:class="key.status === 'revoked' && 'text-ink-gray-5'"
				>
					<td class="border-t border-outline-gray-1 py-2.5 pr-3">
						<span class="flex min-w-0 items-center gap-2">
							<span
								class="truncate text-base-medium"
								:class="key.status === 'active' && 'text-ink-gray-9'"
							>
								{{ key.title }}
							</span>
							<Badge v-if="key.status === 'revoked'" label="Revoked" />
						</span>
						<span
							class="mt-0.5 flex items-center gap-1.5 font-mono text-xs text-ink-gray-5"
						>
							{{ key.masked }}
						</span>
					</td>

					<td
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 text-sm sm:table-cell"
						:class="key.status === 'active' && 'text-ink-gray-6'"
					>
						<Tooltip :text="key.gateway_url">
							<span>{{ geographyLabel(key.geography) }}</span>
						</Tooltip>
					</td>

					<td
						v-if="!sharedLimits"
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 text-sm lg:table-cell"
					>
						<span
							v-if="key.status === 'active'"
							class="flex flex-wrap items-center gap-x-2 text-ink-gray-6"
						>
							<template
								v-for="(chip, index) in limitChips(key.limits)"
								:key="chip.key"
							>
								<span v-if="index" aria-hidden="true">·</span>
								<Tooltip :text="chip.text">
									<span class="tabular-nums">{{ chip.label }}</span>
								</Tooltip>
							</template>
						</span>
					</td>

					<td
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 text-sm md:table-cell"
						:class="key.status === 'active' && 'text-ink-gray-6'"
					>
						<Tooltip :text="formatDateTime(key.creation)">
							<span>{{ timeAgo(key.creation) }}</span>
						</Tooltip>
					</td>

					<td v-if="prepaid" class="border-t border-outline-gray-1 py-2.5 pr-3">
						<template v-if="key.status === 'active'">
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
								<div>
									<div class="text-sm tabular-nums text-ink-gray-5">
										<span class="text-ink-gray-9"
											>{{ usd(key.month_spent) }}</span
										>
										/ {{ usd(key.cap) }}
									</div>
									<div
										class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-gray-2"
										role="meter"
										:aria-valuenow="key.month_spent"
										aria-valuemin="0"
										:aria-valuemax="key.cap"
										:aria-label="`${key.title}: spent this month of its cap`"
									>
										<span
											class="block h-full rounded-full transition-[width] duration-300 ease-out"
											:class="capBarClass(key)"
											:style="{ width: `${capPercent(key)}%` }"
										/>
									</div>
								</div>
							</Tooltip>
						</template>
						<span v-else class="text-sm tabular-nums">
							{{ usd(key.month_spent) }}
						</span>
					</td>

					<td class="border-t border-outline-gray-1 py-2.5 text-right">
						<RowActionsMenu
							v-if="canManage && key.status === 'active'"
							:options="rowActions(key)"
							:label="`Actions for ${key.title}`"
							:busy="busyKey === key.name"
						/>
					</td>
				</tr>
			</tbody>
		</table>

		<p
			v-if="sharedLimits && apiKeys.length"
			class="mt-3 flex flex-wrap items-center gap-x-2 text-p-xs text-ink-gray-5"
		>
			Every key is limited to
			<template v-for="(chip, index) in sharedLimits" :key="chip.key">
				<span v-if="index" aria-hidden="true">·</span>
				<Tooltip :text="chip.text">
					<span class="tabular-nums text-ink-gray-7">{{ chip.label }}</span>
				</Tooltip>
			</template>
		</p>

		<ListViewPagination
			v-if="pageCount > 1"
			class="mt-3"
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
	</section>

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
				<Quickstart v-else :gateway-url="helpGatewayUrl" :models="models" />
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
