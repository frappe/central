<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Dialog,
	type DropdownOptions,
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
import TranslatedText from '@/components/common/TranslatedText.vue'
import Quickstart from '@/components/services/llm/Quickstart.vue'
import { useAI } from '@/composables/useAI'
import { formatDateTime, timeAgo } from '@/lib/datetime'
import { getErrorMessage, reportError } from '@/lib/feedback'
import { limitChips, METRIC_OPTIONS, WINDOW_OPTIONS } from '@/lib/limits'
import { __ } from '@/lib/translate'
import type { AIApiKey } from '@/types/ai'

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
	setLimits,
	limitsSaving,
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
const canSetCaps = computed(
	() => prepaid.value && props.canManage && activeKeys.value.length > 0,
)
const searchable = computed(() => apiKeys.value.length > 6)

const sortedKeys = computed(() =>
	[...apiKeys.value].sort(
		(a, b) => Number(a.status === 'revoked') - Number(b.status === 'revoked'),
	),
)

const PAGE_SIZE = 10

/** A title search over `keys`, shown a page at a time. */
const usePagedSearch = (keys: () => AIApiKey[]) => {
	const query = ref('')
	const page = ref(1)
	const matches = computed(() => {
		const search = query.value.trim().toLowerCase()
		return keys().filter((key) => key.title.toLowerCase().includes(search))
	})
	const pageCount = computed(() => Math.ceil(matches.value.length / PAGE_SIZE))
	const rows = computed(() =>
		matches.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE),
	)
	watch(pageCount, (count) => {
		page.value = Math.min(page.value, Math.max(count, 1))
	})
	watch(query, () => {
		page.value = 1
	})
	return { query, page, matches, pageCount, rows }
}

const {
	query,
	page,
	matches: visibleKeys,
	pageCount,
	rows: pagedKeys,
} = usePagedSearch(() => sortedKeys.value)
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

const rowActions = (key: AIApiKey): DropdownOptions => [
	...(prepaid.value
		? [
				{
					label: __('Set cap'),
					icon: 'lucide-wallet',
					onClick: () => openCaps(key.name),
				},
			]
		: []),
	{
		label: __('Rate limits'),
		icon: 'lucide-gauge',
		onClick: () => openLimits(key),
	},
	{
		label: __('Revoke'),
		icon: 'lucide-trash-2',
		theme: 'red',
		onClick: () => (revokeTarget.value = key),
	},
]

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

const canCreate = computed(
	() =>
		!!newLabel.value.trim() && !!newGeography.value && isValidCap(newCap.value),
)

const create = async (): Promise<void> => {
	if (!canCreate.value) return

	creating.value = true
	createError.value = ''
	try {
		await createApiKey({
			label: newLabel.value.trim(),
			geography: newGeography.value,
			cap: Number(newCap.value),
		})
		createOpen.value = false
	} catch (e) {
		createError.value = getErrorMessage(e)
	} finally {
		creating.value = false
	}
}

const capsOpen = ref(false)
// The one key the dialog is open for, from its row; blank is every live key.
const capsOnly = ref('')
// Keys with no cap yet lead: Save waits on them, so they must not sit on a later page.
const capKeys = computed(() =>
	activeKeys.value
		.filter((key) => !capsOnly.value || key.name === capsOnly.value)
		.sort((a, b) => Number(a.cap >= 1) - Number(b.cap >= 1)),
)
const {
	query: capsQuery,
	page: capsPage,
	matches: capMatches,
	pageCount: capsPageCount,
	rows: capRows,
} = usePagedSearch(() => capKeys.value)
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
const isValidCap = (value: string): boolean =>
	Number.isInteger(Number(value)) && Number(value) >= 1
const capsInvalid = computed(() =>
	capKeys.value.some((key) => !isValidCap(capValues.value[key.name])),
)

const openCaps = (only = ''): void => {
	capsOnly.value = only
	capValues.value = Object.fromEntries(
		activeKeys.value.map((key) => [key.name, String(key.cap)]),
	)
	capsError.value = ''
	capsQuery.value = ''
	capsPage.value = 1
	capsOpen.value = true
}

const saveCaps = async (): Promise<void> => {
	capsError.value = ''
	const changed = Object.fromEntries(
		capKeys.value
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

// One key's own rate limits, edited as rows: a blank model is every model, each counted on its
// own; a row naming one holds there alone. The plan's limits stay above whatever is set here.
interface LimitRow {
	model_key: string
	metric: string
	window: string
	value: string
}
const limitsOpen = ref(false)
const limitsTarget = ref<AIApiKey | null>(null)
const limitRows = ref<LimitRow[]>([])
const limitsError = ref('')
const modelOptions = computed(() => [
	{ label: __('Every model'), value: '' },
	...models.value.map((model) => ({ label: model.name, value: model.name })),
])
const isWholeLimit = (value: string): boolean =>
	Number.isInteger(Number(value)) && Number(value) >= 1
const limitsInvalid = computed(() => {
	const seen = new Set<string>()
	return limitRows.value.some((row) => {
		const slot = `${row.model_key}:${row.metric}:${row.window}`
		if (seen.has(slot) || !isWholeLimit(row.value)) return true
		seen.add(slot)
		return false
	})
})
const addLimitRow = (): void => {
	limitRows.value.push({
		model_key: '',
		metric: 'requests',
		window: '1m',
		value: '',
	})
}
const openLimits = (key: AIApiKey): void => {
	limitsTarget.value = key
	limitRows.value = key.limits.map((limit) => ({
		...limit,
		value: String(limit.value),
	}))
	limitsError.value = ''
	limitsOpen.value = true
	if (modelsGeography.value !== key.geography)
		loadModels(key.geography).catch(reportError)
}
const saveLimits = async (): Promise<void> => {
	if (!limitsTarget.value || limitsInvalid.value) return
	limitsError.value = ''
	try {
		await setLimits(
			limitsTarget.value.name,
			limitRows.value.map((row) => ({ ...row, value: Number(row.value) })),
		)
		limitsOpen.value = false
	} catch (e) {
		limitsError.value = getErrorMessage(e)
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

defineExpose({ openCreate, openHelp })

const revokeTarget = ref<AIApiKey | null>(null)
const revokeError = ref('')

const revoke = async (key: AIApiKey): Promise<void> => {
	revokeError.value = ''
	try {
		await revokeApiKey(key.name)
		revokeTarget.value = null
	} catch (e) {
		revokeError.value = getErrorMessage(e)
	}
}

const geographyDescription = __(
	"Where the key's requests are served. It cannot be changed later: create another key for another geography.",
)
const saveSpendingCapsErrorTitle = __("Couldn't save the spending caps")
const revokePrepaidText = __(
	"Revoke {0}? Any app using it stops working within a few minutes and its cap frees room for another key. This can't be undone.",
)
const revokeText = __(
	"Revoke {0}? Any app using it stops working within a few minutes. This can't be undone.",
)
</script>

<template>
	<section>
		<Teleport v-if="active" defer to="#ai-tab-controls">
			<div class="flex items-center gap-3">
				<TextInput
					v-if="searchable"
					v-model="query"
					class="w-56"
					:placeholder="__('Search keys')"
					:aria-label="__('Search keys by title')"
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
					:label="__('Set caps')"
					icon-left="lucide-wallet"
					@click="openCaps()"
				/>
			</div>
		</Teleport>

		<LoadingText v-if="apiKeysLoading && !apiKeys.length" :lines="3" />

		<div
			v-else-if="apiKeysError && !apiKeys.length"
			class="flex items-center justify-between gap-3 rounded-5 border border-outline-gray-1 px-4 py-3"
		>
			<p class="text-p-sm text-ink-gray-6">
				{{ getErrorMessage(apiKeysError, "Couldn't load your keys.") }}
			</p>
			<Button :label="__('Retry')" @click="loadApiKeys" />
		</div>

		<div
			v-else-if="!apiKeys.length"
			class="flex flex-wrap items-center justify-between gap-3 rounded-5 border border-dashed border-outline-gray-2 px-4 py-3"
		>
			<p class="text-p-sm text-ink-gray-6">
				{{ __('No keys yet. Create one to call the models from your own apps.') }}
			</p>
			<Button
				v-if="canManage"
				:label="__('Create key')"
				icon-left="lucide-plus"
				:disabled="ai?.key_handover_pending"
				@click="openCreate"
			/>
		</div>

		<p
			v-else-if="!visibleKeys.length"
			class="rounded-5 border border-dashed border-outline-gray-2 px-4 py-3 text-p-sm text-ink-gray-6"
		>
			{{ __('No key is named that. Try another name, or clear the search.') }}
		</p>

		<table v-else class="w-full border-separate border-spacing-0 text-left">
			<thead>
				<tr class="text-sm text-ink-gray-5">
					<th scope="col" class="pb-2 font-normal">{{ __('Name') }}</th>
					<th scope="col" class="hidden pb-2 font-normal sm:table-cell">
						{{ __('Geography') }}
					</th>
					<th scope="col" class="hidden pb-2 font-normal lg:table-cell">
						{{ __('Rate limits') }}
					</th>
					<th scope="col" class="hidden pb-2 font-normal md:table-cell">
						{{ __('Created') }}
					</th>
					<th v-if="prepaid" scope="col" class="w-36 pb-2 font-normal">
						{{ __('This month') }}
					</th>
					<th scope="col" class="w-10 pb-2">
						<span class="sr-only">{{ __('Actions') }}</span>
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
							<Badge v-if="key.status === 'revoked'" :label="__('Revoked')" />
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
						class="hidden border-t border-outline-gray-1 py-2.5 pr-3 text-sm lg:table-cell"
					>
						<span
							v-if="key.status === 'active' && key.limits.length"
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
						<Tooltip
							v-else-if="key.status === 'active'"
							:text="__('No limits of its own: the plan\'s apply, counted for the whole team.')"
						>
							<span class="text-ink-gray-5">{{ __('Plan limits') }}</span>
						</Tooltip>
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
								:text="__('Refused until it gets a monthly cap.')"
							>
								<Badge theme="orange" :label="__('No cap yet')" />
							</Tooltip>
							<Tooltip
								v-else
								:text="
									isCapReached(key)
										? __('Cap reached: refused until the month ends or the cap is raised.')
										: __('Spent this month of its {0} monthly cap.', [usd(key.cap)])
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
										:aria-label="__('{0}: spent this month of its cap', [key.title])"
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
							:label="__('Actions for {0}', [key.title])"
							:busy="busyKey === key.name"
						/>
					</td>
				</tr>
			</tbody>
		</table>

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

	<Dialog v-model="helpOpen" :title="__('How to call the models')" size="2xl">
		<template #default>
			<div class="space-y-4">
				<div class="flex items-start justify-between gap-4">
					<p class="text-p-sm text-ink-gray-6">
						{{ __("A key works in its own geography, on both surfaces: point the OpenAI or the Anthropic SDK at that geography's base URL and use it as you would with the vendor.") }}
					</p>
					<Select
						v-model="helpGeography"
						class="w-fit shrink-0"
						:options="geographyOptions"
						:aria-label="__('Geography')"
					>
						<template #prefix>
							<span class="text-ink-gray-5">{{ __('Geography') }}</span>
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

	<Dialog v-model="createOpen" :title="__('Create API key')">
		<template #default>
			<div class="space-y-4">
				<TextInput
					v-model="newLabel"
					:label="__('Title')"
					required
					:placeholder="__('e.g. n8n prod')"
					:description="__('A name to recognise this key by. New keys can take a few minutes to start working.')"
					@keyup.enter="create"
				/>
				<Select
					v-model="newGeography"
					:label="__('Geography')"
					:options="geographyOptions"
					required
					:description="geographyDescription"
				/>
				<TextInput
					v-model="newCap"
					type="number"
					min="1"
					step="1"
					:label="__('Cap (USD)')"
					required
					:placeholder="__('e.g. 10')"
					:description="__('What this key may spend each month.')"
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
					{{ __("Caps and this month's spend take up {0} of your plan's {1} a month, as of {2}.", [usd(spend?.committed ?? 0), usd(spend?.spend_limit ?? 0), asOf]) }}
				</p>
				<Button
					variant="solid"
					:label="__('Create')"
					:loading="creating"
					:disabled="!canCreate"
					@click="create"
				/>
			</div>
		</template>
	</Dialog>

	<Dialog
		v-model="limitsOpen"
		:title="__('Rate limits for {0}', [limitsTarget?.title ?? ''])"
		size="2xl"
	>
		<template #default>
			<Alert
				v-if="limitsError"
				class="mb-4"
				theme="red"
				:title="__('Couldn\'t save the rate limits')"
				:description="limitsError"
			/>
			<p class="mb-3 text-p-sm text-ink-gray-5">
				{{ __("Your plan's limits hold for the whole team. This key's own sit beneath them: whichever is lower refuses first. A row for every model counts each model on its own; a row naming one model holds there alone.") }}
			</p>
			<div
				v-if="limitRows.length"
				class="mb-2 grid grid-cols-[2fr_1fr_1fr_1fr_auto] gap-2 text-sm-medium text-ink-gray-6"
				aria-hidden="true"
			>
				<span>{{ __('Model') }}</span>
				<span>{{ __('Metric') }}</span>
				<span>{{ __('Window') }}</span>
				<span>{{ __('Limit') }}</span>
				<span class="w-7" />
			</div>
			<div class="space-y-2">
				<div
					v-for="(row, index) in limitRows"
					:key="index"
					class="grid grid-cols-[2fr_1fr_1fr_1fr_auto] items-center gap-2"
				>
					<Select
						v-model="row.model_key"
						:options="modelOptions"
						:disabled="limitsSaving || modelsLoading"
						:aria-label="__('Model')"
					/>
					<Select
						v-model="row.metric"
						:options="METRIC_OPTIONS"
						:disabled="limitsSaving"
						:aria-label="__('Metric')"
					/>
					<Select
						v-model="row.window"
						:options="WINDOW_OPTIONS"
						:disabled="limitsSaving"
						:aria-label="__('Window')"
					/>
					<TextInput
						v-model="row.value"
						type="number"
						min="1"
						step="1"
						placeholder="0"
						:aria-label="__('Limit')"
						:disabled="limitsSaving"
						@keyup.enter="saveLimits"
					/>
					<Button
						variant="ghost"
						icon="lucide-x"
						:aria-label="__('Remove this limit')"
						:disabled="limitsSaving"
						@click="limitRows.splice(index, 1)"
					/>
				</div>
			</div>
			<Button
				class="mt-3"
				icon-left="lucide-plus"
				:label="__('Add a limit')"
				:disabled="limitsSaving"
				@click="addLimitRow"
			/>
			<p v-if="!limitRows.length" class="mt-3 text-p-sm text-ink-gray-5">
				{{ __("No limits of its own: the key runs under your plan's alone.") }}
			</p>
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button
					:label="__('Cancel')"
					:disabled="limitsSaving"
					@click="limitsOpen = false"
				/>
				<Button
					variant="solid"
					:label="__('Save')"
					:loading="limitsSaving"
					:disabled="limitsInvalid"
					@click="saveLimits"
				/>
			</div>
		</template>
	</Dialog>

	<Dialog
		v-model="capsOpen"
		:title="capsOnly ? __('Set cap') : __('Set caps')"
		size="2xl"
	>
		<template #default>
			<Alert
				v-if="capsError"
				class="mb-4"
				theme="red"
				:title="saveSpendingCapsErrorTitle"
				:description="capsError"
			/>
			<TextInput
				v-if="capKeys.length > PAGE_SIZE"
				v-model="capsQuery"
				class="mb-4"
				:placeholder="__('Search keys')"
				:aria-label="__('Search keys by title')"
			>
				<template #prefix>
					<span
						class="lucide-search size-4 text-ink-gray-5"
						aria-hidden="true"
					/>
				</template>
			</TextInput>
			<p v-if="!capRows.length" class="py-3 text-p-sm text-ink-gray-6">
				{{ __('No key is named that. Try another name, or clear the search.') }}
			</p>
			<div
				v-else
				class="mb-2 grid grid-cols-[2fr_1fr_1fr_1fr] gap-3 text-sm-medium text-ink-gray-6"
				aria-hidden="true"
			>
				<span class="min-w-0">{{ __('Key') }}</span>
				<span class="text-center">{{ __('Geography') }}</span>
				<span class="text-center">{{ __('Spent this month') }}</span>
				<span>{{ __('Cap (USD)') }}</span>
			</div>
			<div class="space-y-3">
				<div
					v-for="(key, index) in capRows"
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
						min="1"
						step="1"
						:placeholder="__('e.g. 10')"
						:autofocus="index === 0"
						:aria-label="__('Monthly cap for {0} (USD)', [key.title])"
						:disabled="capsSaving"
						@keyup.enter="saveCaps"
					/>
				</div>
			</div>
			<ListViewPagination
				v-if="capsPageCount > 1"
				class="mt-3"
				:page="capsPage"
				:page-count="capsPageCount"
				:page-size="PAGE_SIZE"
				:can-previous="capsPage > 1"
				:can-next="capsPage < capsPageCount"
				:show-page-size="false"
				:count-text="`${capMatches.length} keys`"
				@first="capsPage = 1"
				@previous="capsPage--"
				@next="capsPage++"
				@last="capsPage = capsPageCount"
			/>
			<p class="mt-4 text-p-sm text-ink-gray-5">
				{{ __('Every key needs a cap of at least $1. Spend is as of {0}: The live figure is checked when you save.', [asOf]) }}
			</p>
		</template>
		<template #actions>
			<div class="flex items-center justify-between gap-3">
				<p
					class="max-w-sm text-p-sm"
					:class="capsOverLimit ? 'text-ink-red-6' : 'text-ink-gray-5'"
					aria-live="polite"
				>
					{{ __("{0} of your plan's {1} a month, caps and this month's spend together, as of {2}", [usd(committedTotal), usd(spend?.spend_limit ?? 0), asOf]) }}
				</p>
				<div class="flex items-center gap-2">
					<Button
						:label="__('Cancel')"
						:disabled="capsSaving"
						@click="capsOpen = false"
					/>
					<Button
						variant="solid"
						:label="capsOnly ? __('Save cap') : __('Save caps')"
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
		:title="__('Revoke API key')"
		:confirm-label="__('Revoke')"
		theme="red"
		:loading="busyKey === revokeTarget?.name"
		:error="revokeError"
		@confirm="revoke"
		@after-leave="revokeError = ''"
	>
		<template v-if="revokeTarget">
			<p class="text-p-base text-ink-gray-7">
				<TranslatedText
					:text="
						prepaid
							? revokePrepaidText
							: revokeText
					"
				>
					<template #0>
						<span class="text-base-semibold text-ink-gray-9"
							>{{ revokeTarget.title }}</span
						>
					</template>
				</TranslatedText>
			</p>
		</template>
	</ConfirmDialog>
</template>
