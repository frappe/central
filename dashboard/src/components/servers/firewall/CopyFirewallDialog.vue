<script setup lang="ts">
import { Alert, Checkbox, Dialog } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useServerFirewall } from '@/composables/useServerFirewall'
import type { VirtualMachineRow } from '@/composables/useServers'
import { successToast } from '@/lib/feedback'
import type { Firewall } from '@/lib/firewall'

interface Props {
	/** The saved firewall of the server it comes from. */
	firewall: Firewall
	/** The other servers of the team that can receive the rules. */
	servers: VirtualMachineRow[]
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })

const { updateFirewall, isSaving } = useServerFirewall()
const selected = ref<string[]>([])
const errors = ref<Record<string, string>>({})

watch(open, (isOpen) => {
	if (!isOpen) return

	selected.value = []
	errors.value = {}
})

const titleOf = (resourceId: string): string =>
	props.servers.find((server) => server.resource_id === resourceId)?.title ||
	resourceId

function toggle(resourceId: string, isSelected: boolean): void {
	selected.value = isSelected
		? [...selected.value, resourceId]
		: selected.value.filter((id) => id !== resourceId)
}

const confirmLabel = computed(() =>
	selected.value.length > 1
		? `Copy to ${selected.value.length} servers`
		: 'Copy firewall',
)

async function copy(): Promise<void> {
	const results = await updateFirewall(selected.value, props.firewall)
	errors.value = Object.fromEntries(
		Object.entries(results).filter(
			(entry): entry is [string, string] => entry[1] !== null,
		),
	)

	const copied = selected.value.filter((id) => !errors.value[id])
	if (copied.length)
		successToast(
			`Firewall copied to ${copied.length} server${copied.length > 1 ? 's' : ''}`,
		)
	if (!Object.keys(errors.value).length) open.value = false
	selected.value = Object.keys(errors.value)
}
</script>

<template>
	<Dialog
		v-model="open"
		title="Copy firewall to other servers"
		:actions="[
			{
				label: confirmLabel,
				variant: 'solid',
				disabled: !selected.length,
				loading: isSaving,
				onClick: copy,
			},
		]"
	>
		<template #default>
			<div class="space-y-4">
				<p class="text-p-sm text-ink-gray-6">
					The selected servers get this server's saved firewall, on or off, in
					place of their own. Unsaved changes are not copied.
				</p>

				<Alert
					v-for="(message, resourceId) in errors"
					:key="resourceId"
					theme="red"
					:title="`${titleOf(resourceId)}: ${message}`"
				/>

				<div class="flex flex-col gap-2">
					<Checkbox
						v-for="server in servers"
						:key="server.resource_id"
						:model-value="selected.includes(server.resource_id)"
						:label="server.title || server.resource_id"
						@update:model-value="(value: boolean) => toggle(server.resource_id, value)"
					/>
				</div>
			</div>
		</template>
	</Dialog>
</template>
