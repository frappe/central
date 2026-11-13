<script setup lang="ts">
import { Button, Switch, Tooltip } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import Chip from '@/components/common/Chip.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import ApplyRulesetDialog from '@/components/servers/firewall/ApplyRulesetDialog.vue'
import FirewallRulesEditor from '@/components/servers/firewall/FirewallRulesEditor.vue'
import FirewallRulesTable from '@/components/servers/firewall/FirewallRulesTable.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useFirewallRulesets } from '@/composables/useFirewallRulesets'
import { useServerFirewall } from '@/composables/useServerFirewall'
import { settingsOpen } from '@/composables/useSettings'
import { useUndoHistory } from '@/composables/useUndoHistory'
import { useWireGuardDevices } from '@/composables/useWireGuardDevices'
import { getErrorMessage, reportError, successToast } from '@/lib/feedback'
import {
	type Firewall,
	type FirewallChange,
	type FirewallRules,
	getFirewallTexts,
	getRulesError,
	isSameRule,
	isSameRules,
	PRESETS,
	toCidr,
} from '@/lib/firewall'
import { isMac } from '@/lib/platform'
import { __ } from '@/lib/translate'

interface Props {
	resourceId: string
	/** The server's region, whose WireGuard VPN devices a rule can name. */
	region: string
	isEnabled: boolean
	/** Null until Central first reads the firewall from the region. */
	rules: FirewallRules | null
	canEdit: boolean
	/** The team rulesets this server uses. Empty when it has its own rules. */
	attached: string[]
}

interface FirewallAction {
	change: FirewallChange
	title: string
	confirmLabel: string
	success: string
	warnings: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: [] }>()

// structuredClone refuses Vue's reactive objects, and the rules are plain JSON.
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))

const saved = computed<Firewall | null>(() =>
	props.rules ? { enabled: props.isEnabled, ...props.rules } : null,
)

// Rule edits collect here until Apply, so a swap such as "SSH from the office instead of
// anywhere" never applies half done.
const draft = ref<FirewallRules | null>(null)
const baseline = ref<FirewallRules | null>(null)
const hasUnsavedRules = computed(
	() => JSON.stringify(draft.value) !== JSON.stringify(baseline.value),
)
const pendingChanges = computed(() => {
	if (!baseline.value || !draft.value) return 0
	return (['inbound', 'outbound'] as const).reduce((count, direction) => {
		const before = baseline.value![direction]
		const after = draft.value![direction]
		const removed = before.filter(
			(rule) => !after.some((other) => isSameRule(rule, other)),
		).length
		const added = after.filter(
			(rule) => !before.some((other) => isSameRule(rule, other)),
		).length
		return count + Math.max(removed, added)
	}, 0)
})

const hasIncomplete = ref(false)
const revision = ref(0)
const isDirty = computed(() => hasUnsavedRules.value || hasIncomplete.value)

// Rows keep local state and are keyed by index, so a restored draft remounts them.
function replaceDraft(rules: FirewallRules): void {
	draft.value = rules
	hasIncomplete.value = false
	revision.value++
}

const history = useUndoHistory<FirewallRules>({
	restore: replaceDraft,
	enabled: () => props.canEdit && props.isEnabled && !isSaving.value,
})

function rememberDraft(source?: string): void {
	if (draft.value) history.record(clone(draft.value), source)
}

function resetDraft(rules: FirewallRules | null): void {
	baseline.value = rules && clone(rules)
	draft.value = rules && clone(rules)
	hasIncomplete.value = false
	revision.value++
	history.clear()
}

watch(
	[() => props.resourceId, () => props.rules],
	([resourceId, rules], previous) => {
		if (
			resourceId !== previous?.[0] ||
			(!hasUnsavedRules.value && !hasIncomplete.value)
		)
			resetDraft(rules)
	},
	{ immediate: true },
)

function editRules(rules: FirewallRules, source?: string): void {
	rememberDraft(source)
	draft.value = rules
}

const staleDraft = computed(
	() =>
		!!baseline.value &&
		(!props.rules || !isSameRules(baseline.value, props.rules)),
)
const conflictMessage =
	'The saved firewall rules changed while you were editing. Discard your changes to load the latest rules, then edit again.'
const validation = computed(() => {
	if (staleDraft.value) return conflictMessage
	if (hasIncomplete.value)
		return 'Press Enter to add the address you typed, or clear it.'
	if (!draft.value) return ''
	return (
		getRulesError(draft.value.inbound) || getRulesError(draft.value.outbound)
	)
})
const { updateFirewall, isSaving } = useServerFirewall()
const riskyAction = ref<FirewallAction | null>(null)
const sendError = ref('')

// A change that cuts access asks first. A safe one applies at once.
function confirmIfRisky(action: FirewallAction): void {
	if (action.warnings.length) {
		sendError.value = ''
		riskyAction.value = action
	} else sendChange(action)
}

function toggleFirewall(enabled: boolean): void {
	if (!saved.value) return

	const change =
		enabled && !saved.value.inbound.length && !saved.value.outbound.length
			? { enabled, ...clone(PRESETS[0].rules) }
			: { enabled }
	confirmIfRisky({
		change,
		title: enabled ? 'Turn the firewall on' : 'Turn the firewall off',
		confirmLabel: enabled ? 'Turn on' : 'Turn off',
		success: enabled ? 'Firewall is on' : 'Firewall is off',
		warnings: getFirewallTexts(saved.value, { ...saved.value, ...change }),
	})
}

function saveDraftRules(): void {
	if (
		!saved.value ||
		!draft.value ||
		!hasUnsavedRules.value ||
		validation.value
	)
		return

	confirmIfRisky({
		change: clone(draft.value),
		title: 'Apply firewall changes',
		confirmLabel: 'Apply changes',
		success: 'Firewall rules saved',
		warnings: getFirewallTexts(saved.value, {
			...saved.value,
			...draft.value,
		}),
	})
}

async function sendChange(action: FirewallAction): Promise<void> {
	if (action.change.inbound && staleDraft.value) {
		sendError.value = conflictMessage
		return
	}
	const error = (await updateFirewall([props.resourceId], action.change))[
		props.resourceId
	]
	if (error && riskyAction.value) {
		sendError.value = error
		return
	}
	if (error) {
		reportError(error, { title: "The firewall wasn't changed" })
		return
	}

	riskyAction.value = null
	if (action.change.inbound && action.change.outbound)
		resetDraft({
			inbound: action.change.inbound,
			outbound: action.change.outbound,
		})
	successToast(action.success)
	emit('changed')
}

const resetPreview = ref<boolean | null>(null)

const statusText = computed(() => {
	if (validation.value) return validation.value
	if (!isDirty.value) return 'No unsaved changes'
	if (!pendingChanges.value) return 'Unsaved changes'
	return `${pendingChanges.value} unsaved ${pendingChanges.value === 1 ? 'change' : 'changes'}`
})

const { canManageWireGuard } = useCapabilities()
const { devices } = useWireGuardDevices(canManageWireGuard)
const deviceNames = computed<Record<string, string>>(() =>
	Object.fromEntries(
		devices.value
			.filter((device) => device.region === props.region)
			.map((device) => [toCidr(device.address), device.title]),
	),
)

const { rulesets, apply, reload: reloadRulesets } = useFirewallRulesets()
// Rulesets are managed in Settings, so the list is read again when Settings closes.
watch(settingsOpen, (isOpen) => {
	if (!isOpen) reloadRulesets()
})
const attachedRulesets = computed(() =>
	rulesets.value.filter((item) => props.attached.includes(item.name)),
)
const isApplyingRuleset = ref(false)

async function applyRulesets(names: string[]): Promise<void> {
	await apply(props.resourceId, names)
	successToast(
		names.length
			? __('Rulesets applied')
			: __('Rulesets detached. The rules stay.'),
	)
	emit('changed')
}

/** True when the server uses exactly `names`. A failure is reported and gives false. */
async function keepRulesets(names: string[]): Promise<boolean> {
	try {
		await applyRulesets(names)
		return true
	} catch (failure) {
		reportError(getErrorMessage(failure, __("The ruleset wasn't detached.")), {
			title: __("The firewall wasn't changed"),
		})
		return false
	}
}

// Built-in rules become the server's own draft, so its rulesets are detached first.
async function useBuiltInRules(rules: FirewallRules): Promise<void> {
	if (props.attached.length && !(await keepRulesets([]))) return

	rememberDraft()
	replaceDraft(clone(rules))
}
</script>

<template>
	<SettingsSection
		title="Firewall"
		help="The region filters traffic before it reaches the server."
		description="Choose who can connect to this server, and where the server can connect. Your sites reach the server through Frappe Cloud network, so keep it allowed."
	>
		<template #actions>
			<div v-if="draft" class="flex shrink-0 items-center gap-2">
				<Tooltip
					:text="isDirty ? 'Apply or discard your rule changes first' : undefined"
				>
					<Switch
						:model-value="isEnabled"
						:disabled="!canEdit || isDirty || isSaving"
						@update:model-value="toggleFirewall"
					>
						<template #label><span class="sr-only">Firewall</span></template>
					</Switch>
				</Tooltip>
				<Button
					v-if="canEdit"
					icon-left="lucide-list-checks"
					:label="attached.length ? __('Change rulesets') : __('Apply ruleset')"
					:disabled="isDirty || isSaving"
					@click="isApplyingRuleset = true"
				/>
			</div>
		</template>

		<EmptyState
			v-if="!draft"
			icon="lucide-shield"
			title="Firewall not loaded yet"
			description="It appears after Central next reads this server from its region, within 10 minutes."
		/>

		<EmptyState
			v-else-if="!isEnabled"
			icon="lucide-shield-off"
			title="Firewall is off"
			:description="
				draft.inbound.length || draft.outbound.length
					? 'Every port is open to the internet. Turn it on to use your saved rules again.'
					: 'Every port is open to the internet. Turn it on to allow SSH, HTTP and HTTPS in, and all connections out.'
			"
		/>

		<div v-else class="space-y-6">
			<template v-if="attached.length">
				<div class="space-y-2 rounded-6 bg-surface-gray-1 px-3 py-2">
					<p class="text-p-sm text-ink-gray-7">
						{{ __('This server uses these rulesets and allows what any of them allows. To change a rule, edit its ruleset in Settings. To edit rules here, detach every ruleset.') }}
					</p>
					<ul class="flex flex-wrap gap-1.5">
						<li v-for="item in attachedRulesets" :key="item.name">
							<Chip
								:label="item.title"
								:remove-label="canEdit ? __('Detach {0}', [item.title]) : undefined"
								@remove="keepRulesets(attached.filter((name) => name !== item.name))"
							/>
						</li>
					</ul>
				</div>

				<FirewallRulesTable
					:rules="draft"
					:names="deviceNames"
					:sources="attachedRulesets"
				/>
			</template>

			<FirewallRulesEditor
				v-else
				:rules="draft"
				:disabled="!canEdit || isSaving"
				:names="deviceNames"
				:revision="revision"
				@update="editRules"
				@invalid="hasIncomplete = $event"
			/>

			<footer
				v-if="canEdit && !attached.length"
				class="flex flex-wrap items-center justify-between gap-3 rounded-6 bg-surface-gray-1 py-2 pl-3 pr-2"
			>
				<p
					class="flex min-w-0 flex-1 items-center gap-1.5 text-p-sm text-ink-gray-7"
					role="status"
				>
					<span
						v-if="validation"
						class="lucide-circle-alert size-4 shrink-0 text-ink-amber-6"
						aria-hidden="true"
					/>
					{{ statusText }}
				</p>
				<div class="flex gap-2">
					<Button
						variant="ghost"
						icon-left="lucide-undo-2"
						label="Undo"
						:tooltip="isMac() ? 'Undo (⌘Z)' : 'Undo (Ctrl+Z)'"
						:disabled="!history.canUndo.value || isSaving"
						@click="history.undo()"
					/>
					<Button
						label="Discard"
						:disabled="!isDirty || isSaving"
						@click="resetPreview = true"
					/>
					<Button
						variant="solid"
						label="Apply changes"
						:disabled="!hasUnsavedRules || !!validation"
						:loading="isSaving && !riskyAction"
						@click="saveDraftRules"
					/>
				</div>
			</footer>
		</div>

		<ConfirmDialog
			v-model:target="riskyAction"
			:title="riskyAction?.title ?? ''"
			:confirm-label="riskyAction?.confirmLabel"
			:loading="isSaving"
			:error="sendError"
			@confirm="sendChange"
		>
			<ul class="space-y-2 text-p-sm text-ink-gray-7">
				<li v-for="warning in riskyAction?.warnings" :key="warning">
					{{ warning }}
				</li>
			</ul>
		</ConfirmDialog>

		<ConfirmDialog
			v-model:target="resetPreview"
			title="Discard unsaved changes?"
			confirm-label="Discard changes"
			theme="red"
			@confirm="resetDraft(rules); resetPreview = null"
		>
			<p class="text-p-sm text-ink-gray-7">
				The rules go back to what the server uses now.
			</p>
		</ConfirmDialog>
		<ApplyRulesetDialog
			v-if="saved"
			v-model="isApplyingRuleset"
			:rulesets="rulesets"
			:applied="attached"
			:names="deviceNames"
			:firewall="saved"
			:apply="applyRulesets"
			@preset="useBuiltInRules"
		/>
	</SettingsSection>
</template>
