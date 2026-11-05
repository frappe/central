<script setup lang="ts">
import { Button, Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import {
	createListViewQuery,
	ListView,
	type ListViewColumn,
} from '@/components/common/list-view'
import RowActionsMenu from '@/components/common/RowActionsMenu.vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import {
	type IpVersion,
	usePublicIpv4Pricing,
	useServerAddresses,
} from '@/composables/useServerAddresses'
import { reportError, successToast } from '@/lib/feedback'
import type { ServerOverview } from '@/types/servers'

interface Props {
	server: ServerOverview['server']
	/** The viewer holds server:network on this server. */
	canEdit: boolean
}

interface Address {
	label: string
	value: string
	reach: string
	/** The public address version, or null for the private address. */
	version: IpVersion | null
}

interface AddressChange {
	version: IpVersion
	isAttached: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ changed: [] }>()

const { priceLabel } = usePublicIpv4Pricing(computed(() => props.server.region))
const { setPublicIp, setIpv4Internet, isSaving } = useServerAddresses(
	computed(() => props.server.resource_id),
)

const addresses = computed(() =>
	[
		{
			label: 'Public IPv4',
			value: props.server.public_ipv4,
			reach: 'Anyone on the internet',
			version: 4 as const,
		},
		{
			label: 'Public IPv6',
			value: props.server.public_ipv6,
			reach: 'Anyone on the internet',
			version: 6 as const,
		},
		{
			label: 'Private IPv6',
			value: props.server.ipv6_address,
			reach: props.server.has_wireguard_access
				? 'Your servers and WireGuard VPN devices'
				: 'Your servers in this region',
			version: null,
		},
	].filter((row): row is Address => !!row.value),
)

const query = createListViewQuery()
const columns = computed<ListViewColumn<Address>[]>(() => [
	{ key: 'label', label: 'Type', width: '9rem' },
	{ key: 'value', label: 'Address' },
	{ key: 'reach', label: 'Reachable by', width: '14rem' },
	...(props.canEdit
		? [{ key: 'actions', label: '', width: '2.5rem', align: 'end' as const }]
		: []),
])

const pending = ref<AddressChange | null>(null)
const changeError = ref('')

// Only a paid attach or a detach asks first. IPv6 is free and only adds an address.
function confirmChange(change: AddressChange): void {
	changeError.value = ''
	pending.value = change
}

const confirmation = computed(() => {
	if (!pending.value) return null
	const { version, isAttached } = pending.value
	if (isAttached)
		return {
			title: 'Attach a public IPv4 address',
			message: `Anyone on the internet can reach this server at its new IPv4 address. It costs ${priceLabel.value}, billed while it is attached.`,
			confirmLabel: 'Attach IPv4',
		}
	return {
		title: `Detach the public IPv${version} address`,
		message:
			version === 4
				? "The address goes back to the region and billing stops. You can't get this address back."
				: 'The server can no longer be reached at this address. A new IPv6 address can be different.',
		confirmLabel: 'Detach',
	}
})

function getAddressActions(address: Address) {
	const { version } = address
	if (!version) return []
	return [
		{
			label: 'Detach',
			icon: 'lucide-unlink',
			onClick: () => confirmChange({ version, isAttached: false }),
		},
	]
}

async function changeAddress(change: AddressChange): Promise<void> {
	const { error, isPending } = await setPublicIp(
		change.version,
		change.isAttached,
	)
	if (error && pending.value) {
		changeError.value = error
		return
	}
	if (error) {
		reportError(error, { title: "The address wasn't changed" })
		return
	}

	pending.value = null
	const verb = change.isAttached ? 'attached' : 'detached'
	successToast(
		isPending
			? 'The region is still applying it. The address updates within a few minutes.'
			: `Public IPv${change.version} ${verb}`,
	)
	emit('changed')
}

async function toggleIpv4Internet(enabled: boolean): Promise<void> {
	const error = await setIpv4Internet(enabled)
	if (error) {
		reportError(error, { title: "IPv4 internet access wasn't changed" })
		return
	}

	successToast(
		enabled ? 'IPv4 internet access is on' : 'IPv4 internet access is off',
	)
	emit('changed')
}
</script>

<template>
	<SettingsSection title="Addresses" help="Click an address to copy it.">
		<ListView
			v-if="addresses.length"
			:query="query"
			:rows="addresses"
			:columns="columns"
			:row-key="(row) => row.label"
			:paginated="false"
			:show-count="false"
			item-label="address"
		>
			<template #value="{ row }">
				<CopyableValue :value="row.value" :label="`${row.label} address`" />
			</template>

			<template #actions="{ row }">
				<RowActionsMenu
					:options="getAddressActions(row)"
					:label="`${row.label} options`"
					icon="lucide-ellipsis"
				/>
			</template>
		</ListView>

		<p v-else class="text-p-sm text-ink-gray-5">
			This server has no address yet. It gets one when it finishes setting up.
		</p>

		<div
			v-if="canEdit && (!server.public_ipv4 || !server.public_ipv6)"
			class="flex flex-wrap gap-2 px-2"
		>
			<Button
				v-if="!server.public_ipv4"
				size="sm"
				icon-left="lucide-plus"
				:label="priceLabel ? `Attach IPv4 · ${priceLabel}` : 'Attach IPv4'"
				:disabled="!priceLabel || isSaving"
				:tooltip="priceLabel ? undefined : 'IPv4 pricing unavailable'"
				@click="confirmChange({ version: 4, isAttached: true })"
			/>
			<Button
				v-if="!server.public_ipv6"
				size="sm"
				icon-left="lucide-plus"
				label="Attach IPv6 · Free"
				:loading="isSaving && !pending"
				@click="changeAddress({ version: 6, isAttached: true })"
			/>
		</div>

		<Switch
			:model-value="!!server.has_ipv4_internet"
			:disabled="!canEdit || !!server.public_ipv4 || isSaving"
			label="IPv4 internet access"
			:description="
				server.public_ipv4
					? 'Stays on while the server has a public IPv4 address.'
					: 'Lets the server reach sites that only have IPv4 addresses.'
			"
			class="rounded-6 px-2 py-3"
			@update:model-value="toggleIpv4Internet"
		/>

		<ConfirmDialog
			v-model:target="pending"
			:title="confirmation?.title ?? ''"
			:message="confirmation?.message"
			:confirm-label="confirmation?.confirmLabel"
			:theme="pending?.isAttached ? undefined : 'red'"
			:loading="isSaving"
			:error="changeError"
			@confirm="changeAddress"
		/>
	</SettingsSection>
</template>
