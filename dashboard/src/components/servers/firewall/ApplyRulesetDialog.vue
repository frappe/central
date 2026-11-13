<script setup lang="ts">
import { Alert, Button, Checkbox, Dialog, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import FirewallRulesTable from '@/components/servers/firewall/FirewallRulesTable.vue'
import { openSettings } from '@/composables/useSettings'
import { getErrorMessage } from '@/lib/feedback'
import {
	type Firewall,
	type FirewallRule,
	type FirewallRules,
	getAddressLabel,
	getFirewallTexts,
	getService,
	isCoveredBy,
	isExposedRule,
	isSameRule,
	PRESETS,
} from '@/lib/firewall'
import { __ } from '@/lib/translate'
import type { FirewallRuleset } from '@/types/firewallRulesets'

interface Props {
	rulesets: FirewallRuleset[]
	/** The rulesets the server uses now. Empty when it has its own rules. */
	applied: string[]
	/** Names for known addresses, such as the team's WireGuard VPN devices. */
	names: Record<string, string>
	/** The firewall the server has now, to tell what a new selection would cut off. */
	firewall: Firewall
	/** Makes the server use exactly these rulesets. An empty list detaches all. */
	apply: (rulesets: string[]) => Promise<void>
}

/** One row of the list: a team ruleset or a built-in rule set. */
interface Choice {
	value: string
	title: string
	rules: FirewallRules
	isBuiltIn: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{
	/** The person chose a built-in rule set, which the server gets as its own rules. */
	preset: [rules: FirewallRules]
}>()
const open = defineModel<boolean>({ required: true })

/** The rulesets ticked for the server. */
const checked = ref<string[]>([])
/** The row whose rules the right pane shows. Empty shows the ticked rulesets together. */
const previewed = ref('')
const search = ref('')
const busy = ref(false)
const error = ref('')

const choices = computed<Choice[]>(() => [
	// The applied rulesets come first, so they are in view when the dialog opens.
	...[...props.rulesets]
		.sort(
			(a, b) =>
				Number(props.applied.includes(b.name)) -
				Number(props.applied.includes(a.name)),
		)
		.map((ruleset) => ({
			value: ruleset.name,
			title: ruleset.title,
			rules: ruleset.rules,
			isBuiltIn: false,
		})),
	// A built-in is named by its label, which no ruleset name can match.
	...PRESETS.map((preset) => ({
		value: `built-in:${preset.label}`,
		title: preset.label,
		rules: preset.rules,
		isBuiltIn: true,
	})),
])
const current = computed(() =>
	choices.value.find((choice) => choice.value === previewed.value),
)
const groups = computed(() => {
	const query = search.value.trim().toLowerCase()
	const matches = choices.value.filter((choice) =>
		choice.title.toLowerCase().includes(query),
	)
	return [
		{
			label: __('Your rulesets'),
			choices: matches.filter((choice) => !choice.isBuiltIn),
		},
		{
			label: __('Built-in'),
			choices: matches.filter((choice) => choice.isBuiltIn),
		},
	].filter((group) => group.choices.length)
})
const checkedRulesets = computed(() =>
	props.rulesets.filter((ruleset) => checked.value.includes(ruleset.name)),
)
// What the server gets: every rule of the ticked rulesets, each one once.
const combined = computed<FirewallRules>(() => {
	const rules: FirewallRules = { inbound: [], outbound: [] }
	for (const ruleset of checkedRulesets.value)
		for (const direction of ['inbound', 'outbound'] as const)
			for (const rule of ruleset.rules[direction])
				if (!rules[direction].some((other) => isSameRule(rule, other)))
					rules[direction].push(rule)
	return rules
})
const directions = ['inbound', 'outbound'] as const

const getTitles = (rule: FirewallRule, direction: keyof FirewallRules) =>
	checkedRulesets.value
		.filter((ruleset) =>
			ruleset.rules[direction].some((other) => isSameRule(rule, other)),
		)
		.map((ruleset) => ruleset.title)
		.join(', ')
const getAddresses = (rule: FirewallRule) =>
	rule.cidrs.map((cidr) => getAddressLabel(cidr, props.names)).join(', ')

/** What the selection would cut off. Apply asks again before it goes ahead. */
const risks = computed(() =>
	checked.value.length
		? getFirewallTexts(props.firewall, { enabled: true, ...combined.value })
		: [],
)
/** What a person would not expect from the selection, in plain words. */
const notes = computed(() => {
	const texts: string[] = []
	for (const direction of directions)
		for (const rule of combined.value[direction]) {
			const service = getService(rule).label
			const titles = getTitles(rule, direction)
			const wider = combined.value[direction].find((other) =>
				isCoveredBy(rule, other),
			)
			if (wider)
				texts.push(
					__(
						'{0} for {1} in {2} has no effect. {3} already allows it for {4}.',
						[
							service,
							getAddresses(rule),
							titles,
							getTitles(wider, direction),
							getAddresses(wider),
						],
					),
				)
			if (direction === 'inbound' && isExposedRule(rule))
				texts.push(
					__('{0} is open to anyone on the internet because of {1}.', [
						service,
						titles,
					]),
				)
		}

	// Two rulesets with the same rules each cover the other, so only one of them is named.
	const redundant: FirewallRuleset[] = []
	for (const ruleset of checkedRulesets.value) {
		const others = checkedRulesets.value.filter(
			(other) => other !== ruleset && !redundant.includes(other),
		)
		const isAllowedElsewhere = (
			rule: FirewallRule,
			direction: keyof FirewallRules,
		) =>
			others.some((other) =>
				other.rules[direction].some(
					(same) => isSameRule(rule, same) || isCoveredBy(rule, same),
				),
			)
		if (
			directions.every((direction) =>
				ruleset.rules[direction].every((rule) =>
					isAllowedElsewhere(rule, direction),
				),
			)
		) {
			redundant.push(ruleset)
			texts.push(__('{0} adds no new rules.', [ruleset.title]))
		}
	}
	return texts
})
// A region refuses a firewall with more than 50 addresses.
const addressCount = computed(() =>
	directions
		.flatMap((direction) => combined.value[direction])
		.reduce((count, rule) => count + rule.cidrs.length, 0),
)
/** True after Apply was clicked once with risks on screen. */
const isConfirming = ref(false)

const isChanged = computed(
	() => [...checked.value].sort().join() !== [...props.applied].sort().join(),
)
const applyLabel = computed(() => {
	if (isConfirming.value) return __('Apply anyway')
	if (!checked.value.length) return __('Detach all')
	return checked.value.length === 1
		? __('Apply 1 ruleset')
		: __('Apply {0} rulesets', [checked.value.length])
})

watch(open, (isOpen) => {
	if (!isOpen) return

	checked.value = [...props.applied]
	previewed.value = props.applied.length ? '' : choices.value[0].value
	search.value = ''
	error.value = ''
	isConfirming.value = false
})

function toggle(ruleset: string, isChecked: boolean): void {
	previewed.value = ''
	isConfirming.value = false
	checked.value = isChecked
		? [...checked.value, ruleset]
		: checked.value.filter((name) => name !== ruleset)
}

async function submit(): Promise<void> {
	// A selection that cuts something off is shown first, and applied on the second click.
	if (risks.value.length && !isConfirming.value) {
		previewed.value = ''
		isConfirming.value = true
		return
	}

	busy.value = true
	error.value = ''
	try {
		await props.apply(checked.value)
		open.value = false
	} catch (failure) {
		error.value = getErrorMessage(failure, __("The rulesets weren't applied."))
	} finally {
		busy.value = false
	}
}

function useBuiltIn(rules: FirewallRules): void {
	emit('preset', rules)
	open.value = false
}

// Settings is a dialog too, and it closes at once if it opens while this one still holds focus.
const isOpeningSettings = ref(false)

function manage(): void {
	isOpeningSettings.value = true
	open.value = false
}

function openSettingsAfterClose(): void {
	if (!isOpeningSettings.value) return

	isOpeningSettings.value = false
	openSettings('firewall-rulesets')
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="applied.length ? __('Change rulesets') : __('Apply rulesets')"
		size="4xl"
		@after-leave="openSettingsAfterClose"
	>
		<div class="flex flex-col gap-4">
			<Alert
				v-if="error"
				theme="red"
				:title="__('Couldn\'t apply the rulesets')"
				:description="error"
			/>

			<!-- A fixed height, so the dialog keeps its size as the selection and the search change. -->
			<div class="flex h-96 flex-col gap-4 sm:flex-row sm:gap-0">
				<div
					class="flex max-h-40 min-h-0 flex-col gap-2 sm:max-h-none sm:w-60 sm:shrink-0 sm:border-r sm:border-outline-gray-1 sm:pr-3"
				>
					<TextInput
						v-if="choices.length > 6"
						v-model="search"
						type="search"
						:placeholder="__('Search rulesets')"
						:aria-label="__('Search rulesets')"
					>
						<template #prefix>
							<span
								class="lucide-search size-4 text-ink-gray-5"
								aria-hidden="true"
							/>
						</template>
					</TextInput>

					<div class="min-h-0 flex-1 space-y-3 overflow-y-auto">
						<button
							v-if="rulesets.length"
							type="button"
							class="flex w-full items-center justify-between gap-2 rounded-4 px-2 py-1.5 text-start text-base text-ink-gray-8 focus-visible:focus-ring"
							:class="previewed ? 'hover:bg-surface-gray-1' : 'bg-surface-gray-2'"
							@click="previewed = ''"
						>
							{{ __('Selected rules') }}
							<span class="tabular-nums text-ink-gray-5">
								{{ checked.length }}
							</span>
						</button>

						<div v-for="group in groups" :key="group.label">
							<p class="px-2 pb-1 text-sm text-ink-gray-5">{{ group.label }}</p>
							<div
								v-for="choice in group.choices"
								:key="choice.value"
								class="flex items-center gap-2 rounded-4 px-2"
								:class="choice.value === previewed ? 'bg-surface-gray-2' : 'hover:bg-surface-gray-1'"
							>
								<!-- The lane stays in every row, so the names keep one edge. -->
								<span class="flex w-4 shrink-0">
									<Checkbox
										v-if="!choice.isBuiltIn"
										:model-value="checked.includes(choice.value)"
										:disabled="busy"
										:aria-label="__('Use {0}', [choice.title])"
										@update:model-value="toggle(choice.value, $event)"
									/>
								</span>
								<button
									type="button"
									class="min-w-0 flex-1 truncate rounded-4 py-1.5 text-start text-base text-ink-gray-8 focus-visible:focus-ring"
									@click="previewed = choice.value"
								>
									{{ choice.title }}
								</button>
							</div>
						</div>

						<p
							v-if="!groups.length"
							class="px-2 py-1.5 text-p-sm text-ink-gray-5"
						>
							{{ __('No ruleset matches “{0}”.', [search.trim()]) }}
						</p>
					</div>
				</div>

				<div
					v-if="!previewed"
					class="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto sm:pl-5"
				>
					<header class="space-y-1">
						<h3 class="text-lg-semibold text-ink-gray-8">
							{{ __('Selected rules') }}
						</h3>
						<p class="text-p-sm text-ink-gray-6">
							{{ checked.length ? __('The rules this server gets from the rulesets you selected.') : __('No ruleset is selected. The server keeps its current rules as its own, and you can edit them.') }}
						</p>
					</header>

					<div
						v-for="group in [
							{ texts: risks, icon: 'lucide-triangle-alert text-ink-amber-6' },
							{ texts: notes, icon: 'lucide-info text-ink-gray-5' },
						].filter((item) => item.texts.length)"
						:key="group.icon"
						class="flex gap-2 rounded-6 bg-surface-gray-1 px-3 py-2 text-p-sm text-ink-gray-7"
					>
						<span
							class="mt-0.5 size-4 shrink-0"
							:class="group.icon"
							aria-hidden="true"
						/>
						<ul class="space-y-1">
							<li v-for="text in group.texts" :key="text">{{ text }}</li>
						</ul>
					</div>

					<FirewallRulesTable
						v-if="checked.length"
						:rules="combined"
						:names="names"
						:sources="checkedRulesets"
					/>
				</div>

				<div
					v-else-if="current"
					class="min-h-0 min-w-0 flex-1 space-y-4 overflow-y-auto sm:pl-5"
				>
					<header class="flex items-start justify-between gap-3">
						<div class="min-w-0 space-y-1">
							<h3 class="text-lg-semibold text-ink-gray-8">
								{{ current.title }}
							</h3>
							<p class="text-p-sm text-ink-gray-6">
								{{ current.isBuiltIn ? __('Copied to this server as its own rules, in place of any ruleset. Review them, then click Apply changes.') : __('The server allows what any of its rulesets allows. A change to a ruleset changes the server.') }}
							</p>
						</div>
						<Button
							v-if="current.isBuiltIn"
							class="shrink-0"
							:label="__('Use these rules')"
							:disabled="busy"
							@click="useBuiltIn(current.rules)"
						/>
					</header>

					<FirewallRulesTable :rules="current.rules" :names="names" />
				</div>
			</div>

			<div class="flex flex-wrap items-center justify-between gap-2">
				<Button
					variant="ghost"
					icon-left="lucide-settings"
					:label="__('Manage rulesets')"
					:disabled="busy"
					@click="manage"
				/>
				<div class="flex items-center gap-3">
					<p
						v-if="checked.length"
						class="text-p-sm tabular-nums"
						:class="addressCount > 50 ? 'text-ink-red-6' : 'text-ink-gray-5'"
					>
						{{ __('{0} of 50 addresses', [addressCount]) }}
					</p>
					<Button
						variant="solid"
						:label="applyLabel"
						:loading="busy"
						:disabled="!isChanged || addressCount > 50"
						@click="submit"
					/>
				</div>
			</div>
		</div>
	</Dialog>
</template>
