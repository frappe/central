<script setup lang="ts">
import { Alert, Button, Checkbox, Dialog, FormControl } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
import WireGuardServerList from '@/components/wireguard/WireGuardServerList.vue'
import { getErrorMessage } from '@/lib/feedback'
import { generateKeyPair, isWireGuardKey, type KeyPair } from '@/lib/wireguard'
import type {
	WireGuardDevice,
	WireGuardRegion,
	WireGuardServer,
} from '@/types/wireguard'

interface Props {
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
const emit = defineEmits<{
	/** The private key is empty when the member brought their own key pair. */
	added: [device: WireGuardDevice, privateKey: string]
}>()

const title = ref('')
const region = ref('')
const hasOwnKey = ref(false)
const publicKey = ref('')
const busy = ref(false)
const error = ref('')
// lives only while the dialog is open and never leaves the browser
const generatedKey = ref<KeyPair | null>(null)

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
const regionServers = computed(() =>
	props.servers.filter((server) => server.region === region.value),
)

watch(open, (value) => {
	generatedKey.value = null
	if (!value) return

	title.value = ''
	region.value = props.regions.length === 1 ? props.regions[0].name : ''
	hasOwnKey.value = false
	publicKey.value = ''
	error.value = ''
})

async function getPublicKey(): Promise<string | null> {
	if (hasOwnKey.value) return publicKey.value.trim()

	generatedKey.value ??= await generateKeyPair()
	if (!generatedKey.value) {
		hasOwnKey.value = true
		error.value =
			"This browser can't make WireGuard keys. Paste a public key instead."
		return null
	}
	return generatedKey.value.publicKey
}

async function submit(): Promise<void> {
	if (busy.value || !canSave.value) return
	busy.value = true
	error.value = ''

	try {
		const key = await getPublicKey()
		if (!key) return

		const device = await props.save(region.value, title.value.trim(), key)
		// a team switch closes the dialog, and the device then belongs to the old team
		if (!open.value) return
		emit('added', device, generatedKey.value?.privateKey ?? '')
		open.value = false
	} catch (failure) {
		// keep the key: the request may have reached the gateway before it failed
		error.value = getErrorMessage(failure, "The device couldn't be added.")
	} finally {
		busy.value = false
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		title="Add WireGuard device"
		size="xl"
		:dismissible="!busy"
	>
		<div class="flex flex-col gap-5">
			<p class="text-p-sm text-ink-gray-6">
				The device reaches your servers in one region over their private
				addresses.
			</p>
			<Alert v-if="error" theme="red" :title="error" />
			<div v-if="error && generatedKey" class="flex flex-col gap-2">
				<p class="text-p-sm-medium text-ink-gray-8">Save your private key</p>
				<p class="text-p-sm text-ink-gray-6">
					If the device was created, close this dialog, open its settings, and
					paste this key.
				</p>
				<div class="relative">
					<pre
						class="max-h-40 overflow-auto rounded-6 bg-surface-gray-1 p-3 pr-12 font-mono text-sm text-ink-gray-8"
					>{{ generatedKey.privateKey }}</pre>
					<CopyButton
						class="absolute right-2 top-2"
						size="sm"
						:text="generatedKey.privateKey"
						label="Copy private key"
					/>
				</div>
			</div>
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
						>umask 077; wg genkey > private.key; wg pubkey &lt; private.key</code
					>
					and paste the output. Never paste the private key.
				</p>
			</template>
			<p v-else class="text-p-sm text-ink-gray-5">
				Your browser makes the key pair. Only the public key is sent to Frappe
				Cloud.
			</p>
			<WireGuardServerList v-if="region" :servers="regionServers" />
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
