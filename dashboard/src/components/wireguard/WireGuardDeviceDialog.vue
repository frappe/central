<script setup lang="ts">
import { Alert, Button, Checkbox, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import WireGuardServerList from '@/components/wireguard/WireGuardServerList.vue'
import { getErrorMessage } from '@/lib/feedback'
import {
	buildConfig,
	downloadConfig,
	generateKeyPair,
	isWireGuardKey,
} from '@/lib/wireguard'
import type {
	WireGuardDevice,
	WireGuardRegion,
	WireGuardServer,
} from '@/types/wireguard'

interface Props {
	/** Opens on the settings of a saved device instead of the add form. */
	saved?: WireGuardDevice | null
	regions: WireGuardRegion[]
	servers: WireGuardServer[]
	save: (
		region: string,
		title: string,
		publicKey: string,
	) => Promise<WireGuardDevice>
}

const props = defineProps<Props>()
const open = defineModel<boolean>({ required: true })

const title = ref('')
const region = ref('')
const hasOwnKey = ref(false)
const publicKey = ref('')
const busy = ref(false)
const error = ref('')
const device = ref<WireGuardDevice | null>(null)
// lives only while the dialog is open and never leaves the browser
const privateKey = ref('')
// a save that finishes after the dialog closed must not fill the next opening
let opening = 0

const regionOptions = computed(() =>
	props.regions.map((entry) => ({
		label: entry.display_name || entry.name,
		value: entry.name,
	})),
)
const keyProblem = computed(() =>
	hasOwnKey.value && publicKey.value.trim() && !isWireGuardKey(publicKey.value)
		? 'A WireGuard public key has 44 characters and ends with =.'
		: '',
)
const canSave = computed(
	() =>
		!!title.value.trim() &&
		!!region.value &&
		(!hasOwnKey.value || (!!publicKey.value.trim() && !keyProblem.value)),
)
const config = computed(() =>
	device.value
		? buildConfig(device.value, privateKey.value || '<your private key>')
		: '',
)

watch(open, (value) => {
	opening++
	if (value) {
		device.value = props.saved ?? null
		title.value = ''
		region.value = props.regions.length === 1 ? props.regions[0].name : ''
		hasOwnKey.value = false
		publicKey.value = ''
		error.value = ''
		return
	}
	device.value = null
	privateKey.value = ''
})

async function submit() {
	if (busy.value || !canSave.value) return
	busy.value = true
	error.value = ''
	const current = opening
	try {
		let key = publicKey.value.trim()
		if (!hasOwnKey.value) {
			const pair = await generateKeyPair()
			if (!pair) {
				hasOwnKey.value = true
				error.value =
					"This browser can't make WireGuard keys. Paste a public key instead."
				return
			}
			privateKey.value = pair.privateKey
			key = pair.publicKey
		}
		const saved = await props.save(region.value, title.value.trim(), key)
		if (current === opening) device.value = saved
	} catch (failure) {
		if (current !== opening) return
		privateKey.value = ''
		error.value = getErrorMessage(failure, "The device couldn't be added.")
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="device ? device.title : 'Add WireGuard device'"
		size="xl"
	>
		<div v-if="device" class="flex flex-col gap-5">
			<Alert
				v-if="privateKey"
				theme="amber"
				title="The private key is shown only now"
				description="Download the file before you close this. Central never saw the key and can't show it again."
			/>
			<p v-else class="text-p-sm text-ink-gray-6">
				Put the private key of your device in place of the placeholder.
			</p>

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

			<WireGuardServerList
				:servers="servers.filter((server) => server.region === device?.region)"
			/>

			<div class="flex justify-end gap-2">
				<Button
					icon-left="lucide-download"
					label="Download .conf"
					@click="downloadConfig(device, config)"
				/>
				<Button variant="solid" label="Done" @click="open = false" />
			</div>
		</div>

		<div v-else class="flex flex-col gap-5">
			<p class="text-p-sm text-ink-gray-6">
				The device reaches your servers in one region over their private
				addresses.
			</p>
			<Alert v-if="error" theme="red" :title="error" />
			<FormControl
				v-model="title"
				autofocus
				label="Name"
				placeholder="Work laptop"
			/>
			<FormControl
				v-model="region"
				type="select"
				label="Region"
				:options="regionOptions"
			/>
			<Checkbox v-model="hasOwnKey" label="I have my own key pair" />
			<template v-if="hasOwnKey">
				<FormControl
					v-model="publicKey"
					label="Public key"
					placeholder="HIgo9xNzJMWLKASShiTqIybxZ0U3wGLiUeJ1PKf8ykw="
					:aria-invalid="!!keyProblem"
				/>
				<p v-if="keyProblem" class="text-p-sm text-ink-red-6">
					{{ keyProblem }}
				</p>
				<p v-else class="text-p-sm text-ink-gray-5">
					Run
					<code class="font-mono text-ink-gray-7"
						>wg genkey | tee private.key | wg pubkey</code
					>
					and paste the output. Never paste the private key.
				</p>
			</template>
			<p v-else class="text-p-sm text-ink-gray-5">
				Your browser makes the key pair. Only the public key is sent to Central.
			</p>
			<div class="flex justify-end gap-2">
				<Button label="Cancel" :disabled="busy" @click="open = false" />
				<Button
					label="Add device"
					variant="solid"
					:loading="busy"
					:disabled="!canSave"
					@click="submit"
				/>
			</div>
		</div>
	</Dialog>
</template>
