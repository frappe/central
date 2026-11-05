<script setup lang="ts">
import { Button, Dropdown, Switch, Tooltip } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import CopyFirewallDialog from '@/components/servers/firewall/CopyFirewallDialog.vue'
import FirewallRuleRow from '@/components/servers/firewall/FirewallRuleRow.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useServerFirewall } from '@/composables/useServerFirewall'
import type { VirtualMachineRow } from '@/composables/useServers'
import { useUndoHistory } from '@/composables/useUndoHistory'
import { useWireGuardDevices } from '@/composables/useWireGuardDevices'
import { reportError, successToast } from '@/lib/feedback'
import {
	ANYWHERE_IPV4,
	ANYWHERE_IPV6,
	type Firewall,
	type FirewallChange,
	type FirewallRule,
	type FirewallRules,
	getFirewallTexts,
	getRulesError,
	getService,
	isSameRule,
	isSameRules,
	PRESETS,
	SERVICES,
	toCidr,
} from '@/lib/firewall'
import { isMac } from '@/lib/platform'

type Direction = keyof FirewallRules

interface Props {
	resourceId: string
	/** The server's region, whose WireGuard VPN devices a rule can name. */
	region: string
	isEnabled: boolean
	/** Null until Central first reads the firewall from the region. */
	rules: FirewallRules | null
	canEdit: boolean
	/** The other servers of the team, for Copy to other servers. */
	servers: VirtualMachineRow[]
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

const directions: Direction[] = ['inbound', 'outbound']

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

const incomplete = ref<Record<string, boolean>>({})
const revision = ref(0)
const isDirty = computed(
	() => hasUnsavedRules.value || Object.values(incomplete.value).some(Boolean),
)

// Rows keep local state and are keyed by index, so a restored draft remounts them.
function replaceDraft(rules: FirewallRules): void {
	draft.value = rules
	incomplete.value = {}
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
	incomplete.value = {}
	revision.value++
	history.clear()
}

watch(
	[() => props.resourceId, () => props.rules],
	([resourceId, rules], previous) => {
		if (
			resourceId !== previous?.[0] ||
			(!hasUnsavedRules.value && !Object.values(incomplete.value).some(Boolean))
		)
			resetDraft(rules)
	},
	{ immediate: true },
)

function updateRule(
	direction: Direction,
	index: number,
	rule: FirewallRule,
): void {
	if (!draft.value) return
	rememberDraft(`${direction}:${index}`)
	draft.value[direction][index] = rule
}

function removeRule(direction: Direction, index: number): void {
	if (isSaving.value || !draft.value) return
	rememberDraft()
	const rules = clone(draft.value)
	rules[direction].splice(index, 1)
	replaceDraft(rules)
}

function usePreset(rules: FirewallRules): void {
	presetPreview.value = null
	rememberDraft()
	replaceDraft(clone(rules))
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
	if (Object.values(incomplete.value).some(Boolean))
		return 'Press Enter to add the address you typed, or clear it.'
	if (!draft.value) return ''
	return (
		getRulesError(draft.value.inbound) || getRulesError(draft.value.outbound)
	)
})
function addRule(direction: Direction): void {
	if (!draft.value) return
	const used = draft.value[direction].map((rule) => getService(rule).label)
	const service =
		SERVICES.find(
			(item) =>
				(direction === 'inbound'
					? ['HTTPS', 'HTTP', 'SSH']
					: ['All traffic']
				).includes(item.label) && !used.includes(item.label),
		) ?? SERVICES.find((item) => item.label === 'Custom TCP')!
	rememberDraft()
	draft.value[direction].push({
		protocol: service.protocol,
		ports: service.ports ?? '',
		cidrs: ['SSH', 'Custom TCP', 'Custom UDP'].includes(service.label)
			? []
			: ['0.0.0.0/0', '::/0'],
	})
}

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

const isCopying = ref(false)

const presetPreview = ref<(typeof PRESETS)[number] | null>(null)
const resetPreview = ref<boolean | null>(null)
const menuOptions = computed(() => [
	...(props.isEnabled
		? [
				{
					label: 'Use a preset',
					icon: 'lucide-list-checks',
					submenu: PRESETS.map((preset) => ({
						label: preset.label,
						onClick: () => (presetPreview.value = preset),
					})),
				},
			]
		: []),
	...(props.servers.length
		? [
				{
					label: 'Copy to other servers',
					icon: 'lucide-copy',
					onClick: () => (isCopying.value = true),
				},
			]
		: []),
])

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

function getAddressOptions(direction: Direction): string[] {
	const used = (draft.value?.[direction] ?? [])
		.flatMap((rule) => rule.cidrs)
		.filter((cidr) => ![ANYWHERE_IPV4, ANYWHERE_IPV6].includes(cidr))
	return direction === 'inbound'
		? [...used, ...Object.keys(deviceNames.value)]
		: used
}
</script>

<template>
	<SettingsSection
		title="Firewall"
		help="The region filters traffic before it reaches the server."
		description="Choose who can connect to this server and where it can connect. Keep the private network allowed, so the web console and your sites keep working. Allow a WireGuard VPN device by its name."
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
				<Dropdown
					v-if="canEdit && menuOptions.length"
					:options="menuOptions"
					align="end"
				>
					<Button
						variant="ghost"
						icon="lucide-ellipsis"
						label="Firewall options"
						:disabled="isSaving"
					/>
				</Dropdown>
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
			<section
				v-for="direction in directions"
				:key="direction"
				:aria-label="direction === 'inbound' ? 'Incoming rules' : 'Outgoing rules'"
			>
				<h3 class="px-2 pb-1 text-sm-medium text-ink-gray-8">
					{{ direction === 'inbound' ? 'Incoming' : 'Outgoing' }}
				</h3>

				<div
					class="hidden h-8 items-center gap-x-4 px-2 text-sm text-ink-gray-5 sm:grid sm:grid-cols-[9rem_6rem_minmax(0,1fr)_1.75rem]"
					aria-hidden="true"
				>
					<span>Service</span>
					<span>Port</span>
					<span
						>{{ direction === 'inbound' ? 'Allowed from' : 'Allowed to' }}</span
					>
				</div>

				<FirewallRuleRow
					v-for="(rule, index) in draft[direction]"
					:key="`${revision}:${index}`"
					:rule="rule"
					:index="index"
					:incoming="direction === 'inbound'"
					:disabled="!canEdit || isSaving"
					:options="getAddressOptions(direction)"
					:names="deviceNames"
					@update="updateRule(direction, index, $event)"
					@remove="removeRule(direction, index)"
					@invalid="incomplete[`${direction}:${index}`] = $event"
				/>
				<p
					v-if="!draft[direction].length"
					class="flex min-h-10 items-center px-2 text-sm text-ink-gray-5"
				>
					No {{ direction === 'inbound' ? 'incoming' : 'outgoing' }} connections
					are allowed.
				</p>

				<div v-if="canEdit" class="pt-2">
					<Button
						size="sm"
						variant="ghost"
						icon-left="lucide-plus"
						:label="direction === 'inbound' ? 'Add incoming rule' : 'Add outgoing rule'"
						:disabled="isSaving"
						@click="addRule(direction)"
					/>
				</div>
			</section>

			<footer
				v-if="canEdit"
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
			v-model:target="presetPreview"
			:title="`Use the ${presetPreview?.label ?? ''} preset?`"
			confirm-label="Use preset"
			@confirm="(preset) => usePreset(preset.rules)"
		>
			<p class="text-p-sm text-ink-gray-7">
				{{ presetPreview?.label === 'Private only' ? 'Block public incoming connections. Allow all outgoing connections.' : presetPreview?.label === 'SSH only' ? 'Allow SSH from the internet and all outgoing connections.' : 'Allow SSH, HTTP and HTTPS from the internet and all outgoing connections.' }}
				This replaces your unsaved changes. Review the rules before you apply
				them.
			</p>
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
		<CopyFirewallDialog
			v-if="saved"
			v-model:open="isCopying"
			:firewall="saved"
			:servers="servers"
		/>
	</SettingsSection>
</template>
