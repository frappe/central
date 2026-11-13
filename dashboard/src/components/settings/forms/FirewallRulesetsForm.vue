<script setup lang="ts">
import { Alert, Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import Table from '@/components/common/Table.vue'
import FirewallRulesetDialog from '@/components/servers/firewall/FirewallRulesetDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useFirewallRulesets } from '@/composables/useFirewallRulesets'
import { useWireGuardDevices } from '@/composables/useWireGuardDevices'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { toCidr } from '@/lib/firewall'
import { __ } from '@/lib/translate'
import type { FirewallRuleset } from '@/types/firewallRulesets'

const COLUMNS = [
	{ key: 'title', label: __('Ruleset'), class: 'w-full max-w-0' },
	{ key: 'server_count', label: __('Servers'), class: 'text-right' },
	{ key: 'actions', label: '', class: 'w-10 pr-1' },
]

const { rulesets, loading, error, reload, save, remove } = useFirewallRulesets()
const { canManageNetwork, canManageWireGuard } = useCapabilities()
const { devices } = useWireGuardDevices(canManageWireGuard)
const deviceNames = computed<Record<string, string>>(() =>
	Object.fromEntries(
		devices.value.map((device) => [toCidr(device.address), device.title]),
	),
)

const editing = ref(false)
const selected = ref<FirewallRuleset | null>(null)
const actionError = ref('')

function edit(ruleset: FirewallRuleset | null): void {
	selected.value = ruleset
	editing.value = true
}

async function deleteRuleset(ruleset: FirewallRuleset): Promise<void> {
	if (!confirm(__('Delete the ruleset {0}?', [ruleset.title]))) return

	actionError.value = ''
	try {
		await remove(ruleset.name)
		successToast(__('{0} deleted', [ruleset.title]))
	} catch (failure) {
		actionError.value = getErrorMessage(
			failure,
			__("The ruleset couldn't be deleted."),
		)
	}
}

const getRuleCount = (ruleset: FirewallRuleset): number =>
	ruleset.rules.inbound.length + ruleset.rules.outbound.length

const getActions = (ruleset: FirewallRuleset) =>
	canManageNetwork.value
		? [
				{
					label: __('Edit'),
					icon: 'lucide-pencil',
					onClick: () => edit(ruleset),
				},
				// A ruleset in use is detached from its servers first.
				...(ruleset.server_count
					? []
					: [
							{
								label: __('Delete'),
								icon: 'lucide-trash-2',
								theme: 'red' as const,
								onClick: () => deleteRuleset(ruleset),
							},
						]),
			]
		: []
</script>

<template>
	<div class="space-y-4 pt-6">
		<Teleport defer to="#settings-actions-firewall-rulesets">
			<Button
				v-if="canManageNetwork && rulesets.length"
				:label="__('Add')"
				icon-left="lucide-plus"
				@click="edit(null)"
			/>
		</Teleport>

		<Alert
			v-if="actionError"
			theme="red"
			:title="__('Couldn\'t update your rulesets')"
			:description="actionError"
		/>

		<EmptyState
			v-if="error"
			icon="lucide-cloud-off"
			:title="__('Rulesets couldn\'t load')"
			:description="error"
		>
			<template #action>
				<Button :label="__('Retry')" @click="reload" />
			</template>
		</EmptyState>

		<EmptyState
			v-else-if="!loading && !rulesets.length"
			icon="lucide-shield"
			:title="__('No firewall rulesets yet')"
			:description="__('Define firewall rules once, then apply them to any server from its Networking tab.')"
		>
			<template v-if="canManageNetwork" #action>
				<Button
					:label="__('Add ruleset')"
					icon-left="lucide-plus"
					@click="edit(null)"
				/>
			</template>
		</EmptyState>

		<Table v-else :columns="COLUMNS" :rows="rulesets" height="h-auto">
			<template #title="{ row }">
				<div class="space-y-1 py-2">
					<p class="truncate text-base text-ink-gray-8">{{ row.title }}</p>

					<p class="text-sm text-ink-gray-5">
						{{ getRuleCount(row) === 1 ? __('1 rule') : __('{0} rules', [getRuleCount(row)]) }}
					</p>

					<p v-if="row.last_sync_error" class="truncate text-sm text-ink-red-6">
						{{ row.last_sync_error }}
					</p>
				</div>
			</template>

			<template #server_count="{ row }">
				<span class="text-base tabular-nums text-ink-gray-7">
					{{ row.server_count }}
				</span>
			</template>

			<template #actions="{ row }">
				<RowActionsMenu
					:options="getActions(row)"
					:label="__('Ruleset actions')"
				/>
			</template>
		</Table>

		<FirewallRulesetDialog
			v-model="editing"
			:ruleset="selected"
			:names="deviceNames"
			:save="save"
			@saved="successToast(__('Ruleset saved'))"
		/>
	</div>
</template>
