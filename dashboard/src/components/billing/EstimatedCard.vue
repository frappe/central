<script setup lang="ts">
import {
	Button,
	Dialog,
	FormControl,
	LoadingText,
	Tooltip,
	useCall,
} from 'frappe-ui'
import type { ChartTooltipItem } from 'frappe-ui/charts'
import { ChartTooltip } from 'frappe-ui/charts'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import { whenTeamReady } from '@/composables/useTeamScope'
import { ordinalDate } from '@/lib/date'
import { currencySymbol, money } from '@/lib/format'
import { errorToast, successToast } from '@/lib/toast'
import type { BillingSettings } from '@/types/billing'

// Estimated this cycle — the projected month-end bill, when it bills + days left,
// and the configurable billing alert (spend-alert threshold). Mirrors the FC v2
// prototype: the alert is a quiet ghost button pinned to the card's foot that
// tints amber/red as spend nears/crosses the threshold, and opens a small dialog.
// Reads get_forecast (+ get_billing_settings).
defineProps<{ active?: boolean }>()
defineEmits<{ open: [] }>()
const { forecast, currency } = useBillingOverview()
const { activeTeam } = useSession()
const { canManageBilling } = useCapabilities()

const loading = computed(() => forecast.loading && !forecast.data)
const fc = computed(() => forecast.data)
const projected = computed(() => Number(fc.value?.projected_total ?? 0))
const billsOn = computed(() =>
	fc.value?.period_end ? ordinalDate(fc.value.period_end) : '',
)
const daysRemaining = computed(() => fc.value?.days_remaining ?? null)

// Owed vs inferred. Fall back to treating the whole projection as owed when the
// split is absent (an older cached response), never the other way round — calling
// a fact an estimate is the less honest failure.
const measured = computed(() => Number(fc.value?.measured ?? projected.value))
const estimated = computed(() => Number(fc.value?.estimated ?? 0))
const taxAmount = computed(() => Number(fc.value?.tax_amount ?? 0))
// Nothing accrued yet: the tray would open on an empty list, so the affordance
// that opens it is not offered. An action that leads nowhere is worse than no
// action — it reads as something being broken.
const hasCycle = computed(() => projected.value > 0)

// Against last month. A projected total on its own answers "how much"; the
// question people actually open this for is "is it going up", and that needs the
// month before it. Compared like for like — a full projected month against a
// full billed one — and shown only once there is a month to compare against.
const previousTotal = computed(() => fc.value?.previous_total ?? null)
const previousLabel = computed(() => fc.value?.previous_label ?? null)
const change = computed(() => {
	if (!hasCycle.value || !previousTotal.value || !previousLabel.value)
		return null
	const delta = projected.value - previousTotal.value
	// Under a percent either way is noise, not news.
	if (Math.abs(delta) < previousTotal.value * 0.01) {
		return {
			icon: null,
			amount: null,
			tint: '',
			caption: `About the same as ${previousLabel.value}`,
		}
	}
	const up = delta > 0
	return {
		icon: up ? 'lucide-arrow-up-right' : 'lucide-arrow-down-left',
		amount: money(Math.abs(delta), currency.value),
		tint: up ? 'text-ink-red-7' : 'text-ink-green-7',
		caption: `vs ${previousLabel.value}`,
	}
})
const taxLabel = computed(() => fc.value?.tax_type || 'tax')

const MEASURED_COLOR = 'var(--chart-categorical-1)'
const ESTIMATED_COLOR = 'var(--chart-categorical-2)'
const TAX_COLOR = 'var(--chart-categorical-3)'
const allSegments = computed(() => {
	const rows = [
		{ label: 'So far', amount: measured.value, color: MEASURED_COLOR },
		{
			label: 'Estimated',
			amount: estimated.value,
			color: ESTIMATED_COLOR,
		},
	].filter((row) => row.amount > 0)
	if (taxAmount.value)
		rows.push({
			label: taxLabel.value,
			amount: taxAmount.value,
			color: TAX_COLOR,
		})
	return rows
})

const hiddenSegments = ref<string[]>([])
const isHidden = (label: string): boolean =>
	hiddenSegments.value.includes(label)
const segments = computed(() => {
	const visible = allSegments.value.filter((s) => !isHidden(s.label))
	const total = visible.reduce((t, s) => t + s.amount, 0)
	if (total <= 0) return []
	return visible.map((s) => ({ ...s, pct: (s.amount / total) * 100 }))
})
const pctByLabel = computed(
	() => new Map(segments.value.map((s) => [s.label, s.pct])),
)
function toggleSegment(label: string): void {
	if (!isHidden(label)) {
		if (segments.value.length === 1) return
		hiddenSegments.value = [...hiddenSegments.value, label]
	} else {
		hiddenSegments.value = hiddenSegments.value.filter((l) => l !== label)
	}
}

function formatPercent(percent: number): string {
	if (!percent) return '0%'
	if (percent < 1) return '<1%'
	return `${Math.round(percent)}%`
}

const hovered = ref<string | null>(null)
const dimmed = (label: string): boolean =>
	hovered.value !== null && !isHidden(hovered.value) && hovered.value !== label

const tooltipOpen = ref(false)
const tooltipX = ref(0)
const tooltipY = ref(0)
const tooltipItems = computed<ChartTooltipItem[]>(() => {
	const segment = segments.value.find((s) => s.label === hovered.value)
	if (!segment) return []
	return [
		{
			name: segment.label,
			label: segment.label,
			color: segment.color,
			value: segment.amount,
			formattedValue: money(segment.amount, currency.value),
			percent: segment.pct,
		},
	]
})
function onSegmentEnter(label: string, event: MouseEvent): void {
	hovered.value = label
	tooltipX.value = event.clientX
	tooltipY.value = event.clientY
	tooltipOpen.value = true
}
function onSegmentMove(event: MouseEvent): void {
	if (!tooltipOpen.value) return
	tooltipX.value = event.clientX
	tooltipY.value = event.clientY
}
function onSegmentLeave(): void {
	hovered.value = null
	tooltipOpen.value = false
}

// ── Billing alert (spend-alert threshold) ────────────────────────────────────
// Notify the team once projected spend crosses this amount (0 = off). Stored on
// the Billing Profile via get/save_billing_settings.
const settings = useCall<BillingSettings, { team: string }>({
	url: method(API.billingSettings),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
	refetch: true,
})
const saveAlert = useCall<
	unknown,
	{ team: string; spend_alert_threshold: number }
>({
	url: method(API.saveBillingSettings),
	method: 'POST',
	immediate: false,
})
whenTeamReady(() => settings.reload())

const spendAlert = ref(0)
watch(
	() => settings.data,
	(d) => {
		if (d) spendAlert.value = d.spend_alert_threshold ?? 0
	},
	{ immediate: true },
)

// Alert relationship to the current estimate, so the button says something useful
// at a glance and only tints when it's worth noticing.
const crossed = computed(
	() => spendAlert.value > 0 && projected.value >= spendAlert.value,
)
const near = computed(
	() =>
		spendAlert.value > 0 &&
		!crossed.value &&
		projected.value >= 0.8 * spendAlert.value,
)
const alertLabel = computed(() => {
	if (spendAlert.value <= 0) return 'Set a budget alert'
	if (crossed.value)
		return `Over your ${money(spendAlert.value, currency.value)} alert`
	if (near.value)
		return `Nearing your ${money(spendAlert.value, currency.value)} alert`
	return `Budget alert at ${money(spendAlert.value, currency.value)}`
})
const alertTint = computed(() =>
	crossed.value ? 'text-ink-red-7' : near.value ? 'text-ink-amber-6' : '',
)

// Dialog: edit against a draft so Cancel leaves the live value untouched.
const dialogOpen = ref(false)
const draft = ref(0)
function openDialog(): void {
	draft.value = spendAlert.value
	dialogOpen.value = true
}
async function submitAlert(): Promise<void> {
	try {
		await saveAlert.submit({
			team: activeTeam.value!,
			spend_alert_threshold: Number(draft.value) || 0,
		})
		spendAlert.value = Number(draft.value) || 0
		successToast('Billing alert saved')
		dialogOpen.value = false
		settings.reload()
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<div
		class="rounded-6 border bg-surface-base p-5 transition-colors"
		:class="active ? 'border-outline-gray-4' : 'border-outline-gray-2'"
	>
		<div class="flex h-6 items-center justify-between gap-2">
			<button
				v-if="hasCycle"
				type="button"
				class="text-p-sm text-ink-gray-5 transition-colors hover:text-ink-gray-7"
				@click="$emit('open')"
			>
				This cycle
			</button>
			<span v-else class="text-p-sm text-ink-gray-5">This cycle</span>
			<div class="flex items-center gap-0.5">
				<Tooltip v-if="canManageBilling" :text="alertLabel">
					<button
						type="button"
						class="grid size-6 place-items-center rounded-4 transition-colors hover:bg-surface-gray-2"
						:class="
							alertTint || 'text-ink-gray-4 hover:text-ink-gray-6'
						"
						aria-label="Budget alert"
						@click="openDialog"
					>
						<span class="lucide-bell size-4" aria-hidden="true" />
					</button>
				</Tooltip>
				<button
					v-if="hasCycle"
					type="button"
					class="grid size-6 place-items-center rounded-4 text-ink-gray-4 hover:bg-surface-gray-2 hover:text-ink-gray-6"
					aria-label="Breakdown"
					@click="$emit('open')"
				>
					<span class="lucide-chevron-right size-4" aria-hidden="true" />
				</button>
			</div>
		</div>

		<div v-if="loading" class="mt-2 w-40">
			<LoadingText :lines="2" />
		</div>
		<template v-else>
			<div class="mt-1.5 flex flex-wrap items-baseline gap-x-2.5">
				<span class="text-2xl-semibold tabular-nums text-ink-gray-9">
					{{ money(projected, currency) }}
				</span>
				<span v-if="change" class="flex min-w-0 items-center gap-1 text-sm">
					<span
						v-if="change.icon"
						class="size-4 shrink-0"
						:class="[change.tint, change.icon]"
						aria-hidden="true"
					/>
					<span
						v-if="change.amount"
						class="text-sm-medium tabular-nums"
						:class="change.tint"
					>
						{{ change.amount }}
					</span>
					<span class="truncate text-ink-gray-5">{{ change.caption }}</span>
				</span>
			</div>
			<p class="mt-1 text-p-sm text-ink-gray-5">
				<template v-if="!hasCycle">
					Nothing has been billed yet this cycle
				</template>
				<template v-else>
					<template v-if="billsOn">Bills {{ billsOn }}</template>
					<template v-if="daysRemaining != null">
						· {{ daysRemaining }} days left</template
					>
				</template>
			</p>

			<template v-if="segments.length">
				<div class="mt-4 flex h-2 gap-0.5" aria-hidden="true">
					<span
						v-for="segment in segments"
						:key="segment.label"
						class="h-full rounded-[4px] transition-[opacity,transform,width] duration-150"
						:class="[
							dimmed(segment.label) ? 'opacity-75' : '',
							hovered === segment.label ? 'scale-y-125' : '',
						]"
						:style="{ width: `${segment.pct}%`, backgroundColor: segment.color }"
						@mouseenter="onSegmentEnter(segment.label, $event)"
						@mousemove="onSegmentMove"
						@mouseleave="onSegmentLeave"
					/>
				</div>
				<ChartTooltip
					:open="tooltipOpen"
					:x="tooltipX"
					:y="tooltipY"
					:items="tooltipItems"
				/>
				<div class="mt-1.5 flex flex-wrap items-center gap-x-1 gap-y-0.5">
					<Button
						v-for="segment in allSegments"
						:key="segment.label"
						variant="ghost"
						size="xs"
						:aria-pressed="!isHidden(segment.label)"
						:label="`${isHidden(segment.label) ? 'Show' : 'Hide'} ${segment.label}`"
						@click="toggleSegment(segment.label)"
						@mouseenter="hovered = segment.label"
						@mouseleave="hovered = null"
						@focus="hovered = segment.label"
						@blur="hovered = null"
					>
						<span class="flex items-center gap-1.5">
							<span
								class="size-2 shrink-0 rounded-full"
								:class="isHidden(segment.label) ? 'opacity-30' : ''"
								:style="{ backgroundColor: segment.color }"
							/>
							<span
								:class="
									isHidden(segment.label) ? 'text-ink-gray-4' : 'text-ink-gray-6'
								"
							>
								{{ segment.label }}
							</span>
							<span
								v-if="!isHidden(segment.label)"
								class="tabular-nums text-ink-gray-4"
							>
								{{ formatPercent(pctByLabel.get(segment.label) ?? 0) }}
							</span>
						</span>
					</Button>
				</div>
			</template>
		</template>

		<Dialog v-model:open="dialogOpen" title="Set a budget alert">
			<template #default>
				<FormControl
					v-model="draft"
					type="number"
					:label="`Alert me above (${currencySymbol(currency)})`"
					min="0"
					placeholder="20000"
				/>
				<p class="mt-2 text-p-sm text-ink-gray-5">
					We'll notify the team once projected spend crosses this. Set 0 to turn
					it off.
				</p>
			</template>
			<template #actions>
				<div class="flex justify-end gap-2">
					<Button label="Cancel" @click="dialogOpen = false" />
					<Button
						variant="solid"
						label="Set alert"
						:loading="saveAlert.loading"
						@click="submitAlert"
					/>
				</div>
			</template>
		</Dialog>
	</div>
</template>
