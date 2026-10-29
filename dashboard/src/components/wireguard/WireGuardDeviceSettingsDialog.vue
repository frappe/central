<script setup lang="ts">
import { Alert, Button, Dialog } from 'frappe-ui'
import { renderSVG } from 'uqr'
import { computed } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import WireGuardServerList from '@/components/wireguard/WireGuardServerList.vue'
import { buildConfig, downloadConfig } from '@/lib/wireguard'
import type { OpenedWireGuardDevice, WireGuardServer } from '@/types/wireguard'

interface Props {
	servers: WireGuardServer[]
}

const props = defineProps<Props>()
const target = defineModel<OpenedWireGuardDevice | null>('target', {
	required: true,
})
const device = computed(() => target.value?.device ?? null)
const privateKey = computed(() => target.value?.privateKey ?? '')

const config = computed(() =>
	device.value
		? buildConfig(device.value, privateKey.value || '<your private key>')
		: '',
)
const qrCode = computed(
	() =>
		privateKey.value &&
		`data:image/svg+xml;utf8,${encodeURIComponent(renderSVG(config.value))}`,
)
const regionServers = computed(() =>
	props.servers.filter((server) => server.region === device.value?.region),
)

function close(): void {
	target.value = null
}
</script>

<template>
	<Dialog
		:model-value="!!device"
		:title="device?.title"
		size="xl"
		@update:model-value="(open: boolean) => !open && close()"
	>
		<div v-if="device" class="flex flex-col gap-5">
			<Alert
				v-if="privateKey"
				theme="amber"
				title="This file is available only now"
				description="Frappe Cloud never saw the key and can't show it again."
			/>

			<ol class="list-decimal space-y-1 pl-5 text-p-sm text-ink-gray-7">
				<li>
					Install the
					<a
						href="https://www.wireguard.com/install/"
						target="_blank"
						rel="noopener"
						class="text-p-sm-medium text-ink-gray-8 hover:underline"
						>WireGuard app</a
					>.
				</li>
				<li v-if="privateKey">
					Scan the code with a phone, or download the file on a computer and
					import it.
				</li>
				<li v-else>Copy the file, add your private key, and import it.</li>
				<li>
					Turn on the tunnel and copy an SSH command below.
					<a
						href="https://frappe.github.io/central/servers/wireguard#connect"
						target="_blank"
						rel="noopener"
						class="text-p-sm-medium text-ink-gray-8 hover:underline"
						>Steps for each device</a
					>
				</li>
			</ol>

			<img
				v-if="qrCode"
				:src="qrCode"
				alt="QR code of the WireGuard file for the mobile app"
				class="size-48 self-center rounded-6 bg-white p-2"
			/>

			<div class="relative">
				<pre
					class="max-h-60 overflow-auto rounded-6 bg-surface-gray-1 p-3 font-mono text-sm text-ink-gray-8"
				>{{ config }}</pre>
				<CopyButton
					class="absolute right-2 top-2"
					size="sm"
					:text="config"
					label="Copy WireGuard file"
				/>
			</div>

			<WireGuardServerList :servers="regionServers" />

			<div class="flex justify-end gap-2">
				<Button
					v-if="privateKey"
					icon-left="lucide-download"
					label="Download .conf"
					@click="downloadConfig(device, config)"
				/>
				<Button variant="solid" label="Done" @click="close" />
			</div>
		</div>
	</Dialog>
</template>
