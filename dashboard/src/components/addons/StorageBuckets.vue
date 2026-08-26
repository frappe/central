<script setup lang="ts">
import {
	Badge,
	Button,
	Dialog,
	Dropdown,
	type DropdownOptions,
	FormControl,
	Spinner,
} from 'frappe-ui'
import { ListRowItem, ListView as UntypedListView } from 'frappe-ui/experimental'
import { type Component, computed, ref, watch } from 'vue'

import EmptyState from '@/components/common/EmptyState.vue'
import type {
	RevealedBucket,
	StorageBucket,
} from '@/composables/useObjectStorage'
import { useObjectStorage } from '@/composables/useObjectStorage'
import { errorToast, successToast } from '@/lib/toast'

const props = defineProps<{ managedService: string; canManage: boolean }>()

// The experimental ListView is a legacy JS SFC, so its slots carry no types.
const ListView = UntypedListView as Component

const {
	buckets,
	bucketsLoading,
	busyBucket,
	loadBuckets,
	createBucket,
	revealBucketKey,
	revokeBucketKey,
} = useObjectStorage()

watch(
	() => props.managedService,
	(managed) => {
		if (managed) loadBuckets(managed)
	},
	{ immediate: true },
)

// Numeric widths are fr units (ListView convention) so the bucket column stretches
// and the rest keep to their content; actions stays a fixed icon-sized column.
const columns = [
	{ label: 'Bucket', key: 'label', align: 'left', width: 2 },
	{ label: 'Access key', key: 'masked_key', align: 'left', width: 2 },
	{ label: 'Region', key: 'region', align: 'left', width: 1 },
	{ label: 'Status', key: 'status', align: 'left', width: '7rem' },
	{ label: '', key: 'actions', align: 'right', width: '3rem' },
]

const search = ref('')

// The name being provisioned. Garage takes a few calls to answer, so the bucket
// shows in the list as pending rather than appearing out of nowhere at the end.
const pendingName = ref('')
const PENDING_KEY = '__pending__'

const rows = computed(() => {
	const term = search.value.trim().toLowerCase()
	const listed = term
		? buckets.value.filter((bucket) =>
				`${bucket.label} ${bucket.provider_ref ?? ''}`
					.toLowerCase()
					.includes(term),
			)
		: buckets.value

	if (!pendingName.value) return listed

	const pending = {
		name: PENDING_KEY,
		label: pendingName.value,
		status: 'Provisioning',
		gateway_url: null,
		provider_ref: null,
		service_backend: null,
		region: null,
		creation: '',
		masked_key: 'minting key…',
	} satisfies StorageBucket

	return [pending, ...listed]
})

const details = ref<RevealedBucket | null>(null)
const secretRevealed = ref(false)

watch(details, () => (secretRevealed.value = false))

const createOpen = ref(false)
const newName = ref('')
const creating = ref(false)


const openCreate = (): void => {
	newName.value = ''
	createOpen.value = true
}

const create = async (): Promise<void> => {
	const bucket = newName.value.trim()
	if (!bucket || creating.value) return

	creating.value = true
	pendingName.value = bucket
	try {
		details.value = await createBucket(bucket)
		createOpen.value = false
	} catch (e) {
		errorToast(e)
	} finally {
		creating.value = false
		pendingName.value = ''
	}
}

const revealingName = ref('')

const reveal = async (bucket: StorageBucket): Promise<void> => {
	revealingName.value = bucket.name
	try {
		details.value = await revealBucketKey(bucket.name)
	} catch (e) {
		errorToast(e)
	} finally {
		revealingName.value = ''
	}
}

const pendingRevoke = ref<StorageBucket | null>(null)

const confirmRevoke = async (): Promise<void> => {
	const bucket = pendingRevoke.value
	pendingRevoke.value = null
	if (bucket) await revokeBucketKey(bucket.name)
}

const rowActions = (bucket: StorageBucket): DropdownOptions => [
	{
		label: 'Reveal credentials',
		icon: 'lucide-eye',
		onClick: () => reveal(bucket),
	},
	{
		label: 'Revoke key',
		icon: 'lucide-trash-2',
		theme: 'red',
		onClick: () => (pendingRevoke.value = bucket),
	},
]

const maskedSecret = computed(() => {
	if (!details.value) return ''
	const secret = details.value.secret_access_key

	return secretRevealed.value
		? secret
		: `${secret.slice(0, 6)}${'•'.repeat(24)}${secret.slice(-4)}`
})

const copy = async (value: string, label: string): Promise<void> => {
	await navigator.clipboard.writeText(value)
	successToast(`${label} copied`)
}
</script>

<template>
	<div class="space-y-2">
		<div class="flex items-center justify-between gap-3">
			<p class="text-base-medium text-ink-gray-8">Buckets</p>

			<Button
				v-if="canManage"
				variant="subtle"
				icon-left="lucide-plus"
				label="Create bucket"
				@click="openCreate"
			/>
		</div>

		<FormControl
			v-if="buckets.length > 5"
			v-model="search"
			type="text"
			placeholder="Search buckets"
			autocomplete="off"
		>
			<template #prefix>
				<span class="lucide-search size-4 text-ink-gray-5" />
			</template>
		</FormControl>

		<div v-if="bucketsLoading && !buckets.length" class="flex h-40 justify-center py-12">
			<Spinner class="size-5 text-ink-gray-5" />
		</div>

		<EmptyState
			v-else-if="!buckets.length"
			icon="lucide-archive"
			title="No buckets yet"
			description="Create one and we'll mint the key that reaches it."
		>
			<template v-if="canManage" #action>
				<Button
					variant="subtle"
					icon-left="lucide-plus"
					label="Create bucket"
					@click="openCreate"
				/>
			</template>
		</EmptyState>

		<p v-else-if="!rows.length" class="py-12 text-center text-p-sm text-ink-gray-5">
			No buckets match “{{ search }}”.
		</p>

		<ListView
			v-else
			:columns="columns"
			:rows="rows"
			row-key="name"
			:options="{ selectable: false, showTooltip: false }"
		>
			<template #cell="{ column, row, item }">
				<span
					v-if="column.key === 'label'"
					class="truncate font-mono"
					:class="row.name === PENDING_KEY ? 'text-ink-gray-5' : 'text-ink-gray-8'"
				>
					{{ row.label }}
				</span>

				<span
					v-else-if="column.key === 'masked_key'"
					class="truncate font-mono text-ink-gray-5"
				>
					{{ row.masked_key }}
				</span>

				<div
					v-else-if="column.key === 'status' && row.name === PENDING_KEY"
					class="flex items-center gap-2 text-p-sm text-ink-gray-5"
				>
					<Spinner class="size-3.5" />
					Creating…
				</div>

				<Badge
					v-else-if="column.key === 'status'"
					:theme="row.status === 'Active' ? 'green' : 'gray'"
					variant="subtle"
					:label="row.status"
				/>

				<div v-else-if="column.key === 'actions'" class="flex justify-end">
					<Dropdown
						v-if="canManage && row.status === 'Active' && row.name !== PENDING_KEY"
						:options="rowActions(row)"
						align="end"
					>
						<template #trigger>
							<Button
								variant="ghost"
								size="sm"
								icon="lucide-ellipsis-vertical"
								label="Bucket actions"
								tooltip="Bucket actions"
								:loading="busyBucket === row.name || revealingName === row.name"
								@click.stop
							/>
						</template>
					</Dropdown>
				</div>

				<ListRowItem
					v-else
					:column="column"
					:row="row"
					:item="item"
					:align="column.align"
				/>
			</template>
		</ListView>
	</div>

	<!-- Closing mid-flight would strand the caller: the bucket still gets created and
	     its secret is shown once. Dismissal is refused until the call settles. -->
	<Dialog
		:model-value="createOpen"
		title="Create bucket"
		size="md"
		:options="{ backdropDismiss: !creating, showCloseButton: !creating }"
		@update:model-value="
			(v: boolean) => {
				if (!v && !creating) createOpen = false
			}
		"
	>
		<FormControl
			v-model="newName"
			type="text"
			label="Name"
			placeholder="e.g. acme-backups"
			description="3-63 characters: lowercase letters, digits, dots and hyphens. Names are shared across all customers, so a taken one is refused."
			autocomplete="off"
			:disabled="creating"
			@keyup.enter="create"
		/>

		<p v-if="creating" class="mt-3 flex items-center gap-2 text-p-sm text-ink-gray-5">
			<Spinner class="size-3.5" />
			Creating the bucket and minting its key. This can take a few seconds.
		</p>

		<div class="mt-4 flex justify-end gap-2">
			<Button
				variant="ghost"
				label="Cancel"
				:disabled="creating"
				@click="createOpen = false"
			/>
			<Button
				variant="solid"
				:label="creating ? 'Creating…' : 'Create'"
				:loading="creating"
				:disabled="!newName.trim() || creating"
				@click="create"
			/>
		</div>
	</Dialog>

	<Dialog
		:model-value="!!details"
		:title="details ? `Bucket - ${details.bucket}` : ''"
		size="2xl"
		@update:model-value="
			(v: boolean) => {
				if (!v) details = null
			}
		"
	>
		<template #default>
			<div v-if="details" class="space-y-5">
				<p class="text-p-sm text-ink-gray-6">
					Add these under Object storage in a bench's settings, or in any
					S3-compatible client. The secret is shown here and nowhere else.
				</p>

				<FormControl
					type="text"
					label="Endpoint URL"
					:model-value="details.endpoint_url"
					readonly
				>
					<template #suffix>
						<Button
							variant="ghost"
							size="sm"
							icon="lucide-copy"
							label="Copy endpoint URL"
							tooltip="Copy"
							@click="copy(details.endpoint_url, 'Endpoint URL')"
						/>
					</template>
				</FormControl>

				<FormControl
					type="text"
					label="Bucket"
					:model-value="details.bucket"
					readonly
				>
					<template #suffix>
						<Button
							variant="ghost"
							size="sm"
							icon="lucide-copy"
							label="Copy bucket name"
							tooltip="Copy"
							@click="copy(details.bucket, 'Bucket name')"
						/>
					</template>
				</FormControl>

				<FormControl
					type="text"
					label="Access key"
					:model-value="details.access_key_id"
					readonly
				>
					<template #suffix>
						<Button
							variant="ghost"
							size="sm"
							icon="lucide-copy"
							label="Copy access key"
							tooltip="Copy"
							@click="copy(details.access_key_id, 'Access key')"
						/>
					</template>
				</FormControl>

				<FormControl
					type="text"
					label="Secret key"
					:model-value="maskedSecret"
					readonly
					description="Treat it like a password. Revoking it leaves the bucket and its objects untouched."
				>
					<template #suffix>
						<div class="flex items-center">
							<Button
								variant="ghost"
								size="sm"
								:icon="secretRevealed ? 'lucide-eye-off' : 'lucide-eye'"
								:label="secretRevealed ? 'Hide secret' : 'Reveal secret'"
								:tooltip="secretRevealed ? 'Hide' : 'Reveal'"
								@click="secretRevealed = !secretRevealed"
							/>
							<Button
								variant="ghost"
								size="sm"
								icon="lucide-copy"
								label="Copy secret key"
								tooltip="Copy"
								@click="copy(details.secret_access_key, 'Secret key')"
							/>
						</div>
					</template>
				</FormControl>
			</div>
		</template>
	</Dialog>

	<Dialog
		:model-value="!!pendingRevoke"
		title="Revoke bucket key"
		size="md"
		@update:model-value="
			(v: boolean) => {
				if (!v) pendingRevoke = null
			}
		"
	>
		<p class="text-p-base text-ink-gray-7">
			Revoke the key for
			<span class="break-all font-semibold text-ink-gray-8">
				{{ pendingRevoke?.label }}
			</span>
			? Anything using it stops working immediately. The bucket and its objects
			are kept.
		</p>

		<div class="mt-4 flex justify-end gap-2">
			<Button variant="ghost" label="Cancel" @click="pendingRevoke = null" />
			<Button
				variant="solid"
				theme="red"
				label="Revoke"
				:loading="busyBucket === pendingRevoke?.name"
				@click="confirmRevoke"
			/>
		</div>
	</Dialog>
</template>
