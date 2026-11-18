<script setup lang="ts">
import { Alert, Button, Dialog } from 'frappe-ui'
import { renderSVG } from 'uqr'
import { computed } from 'vue'
import {
	buildConfig,
	downloadConfig,
	PRIVATE_KEY_PLACEHOLDER,
	WIREGUARD_DOCS_URL,
} from '@/lib/wireguard'
import type { OpenedWireGuardDevice } from '@/types/wireguard'

const target = defineModel<OpenedWireGuardDevice | null>('target', {
	required: true,
})
const device = computed(() => target.value?.device ?? null)
const privateKey = computed(() => target.value?.privateKey ?? '')

// The code carries the private key, so it exists only when the browser made the key.
const qrCode = computed(
	() =>
		device.value &&
		privateKey.value &&
		`data:image/svg+xml;utf8,${encodeURIComponent(renderSVG(buildConfig(device.value, privateKey.value)))}`,
)

function close(): void {
	target.value = null
}
</script>

<template>
	<Dialog
		:model-value="!!device"
		:title="device ? `Connect ${device.title}` : ''"
		size="lg"
		@update:model-value="(open: boolean) => !open && close()"
	>
		<div v-if="device" class="flex flex-col gap-5">
			<Alert
				v-if="privateKey"
				theme="blue"
				title="Download the file now"
				description="Frappe Cloud never saw the private key and can't show it again."
			/>

			<ol class="list-decimal space-y-1.5 pl-5 text-p-sm text-ink-gray-7">
				<li>
					Install the
					<a
						href="https://www.wireguard.com/install/"
						target="_blank"
						rel="noopener"
						class="text-p-sm-medium text-ink-gray-8 underline"
						>WireGuard app</a
					>.
				</li>
				<li v-if="privateKey">
					Scan the code with a phone, or download the file on a computer and
					import it.
				</li>
				<li v-else>
					Download the file, replace
					<code class="font-mono text-ink-gray-8"
						>{{ PRIVATE_KEY_PLACEHOLDER }}</code
					>
					with your private key, and import it.
				</li>
				<li>
					Turn on the firewall of the device and block incoming traffic from the
					tunnel. Your servers can reach this device too.
					<a
						:href="`${WIREGUARD_DOCS_URL}#protect-the-device`"
						target="_blank"
						rel="noopener"
						class="text-p-sm-medium text-ink-gray-8 underline"
						>Read how to protect the device</a
					>
				</li>
				<li>
					Turn on the tunnel, then connect over SSH to a server that has
					WireGuard VPN on.
					<a
						:href="`${WIREGUARD_DOCS_URL}#connect`"
						target="_blank"
						rel="noopener"
						class="text-p-sm-medium text-ink-gray-8 underline"
						>Read the steps for each device</a
					>
				</li>
			</ol>

			<img
				v-if="qrCode"
				:src="qrCode"
				alt="QR code of the WireGuard VPN file for the mobile app"
				class="size-48 self-center rounded-6 bg-white p-2"
			/>
		</div>

		<template v-if="device" #actions>
			<div class="flex justify-end gap-2">
				<Button label="Done" @click="close" />
				<Button
					variant="solid"
					icon-left="lucide-download"
					label="Download .conf"
					@click="downloadConfig(device, privateKey)"
				/>
			</div>
		</template>
	</Dialog>
</template>
