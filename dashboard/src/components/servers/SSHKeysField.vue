<script setup lang="ts">
import { Alert, Button, Popover } from 'frappe-ui'
import { computed, ref } from 'vue'
import SSHKeyDialog from '@/components/servers/SSHKeyDialog.vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useTeamSSHKeys } from '@/composables/useTeamSSHKeys'
import type { TeamSSHKey } from '@/types/sshKeys'

interface Props {
	modelValue: string[]
	required: boolean
}

const props = defineProps<Props>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const { keys, loading, error, reload, create } = useTeamSSHKeys()
const { canManageSSHKeys } = useCapabilities()
const open = ref(false)
const adding = ref(false)
const chosen = computed(() =>
	keys.value.filter((key) => props.modelValue.includes(key.name)),
)

function toggle(name: string) {
	const next = props.modelValue.includes(name)
		? props.modelValue.filter((value) => value !== name)
		: [...props.modelValue, name]
	emit('update:modelValue', next)
}

function saved(key: TeamSSHKey | null) {
	if (key) emit('update:modelValue', [...props.modelValue, key.name])
	open.value = false
}
</script>

<template>
	<div class="flex flex-col gap-2">
		<label class="text-p-sm font-medium text-ink-gray-8"
			>SSH keys{{ required ? '' : ' (optional)' }}</label
		>
		<Popover v-model:open="open" align="start" :offset="5">
			<template #trigger>
				<button
					type="button"
					class="flex w-full items-center justify-between rounded-5 border border-outline-gray-2 bg-surface-base px-3 py-2 text-left text-p-sm text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-outline-gray-4"
					aria-label="Select SSH keys"
				>
					<span class="truncate"
						>{{ chosen.length ? chosen.map((key) => key.title).join(', ') : 'Select team SSH keys' }}</span
					>
					<span
						class="lucide-chevron-down size-4 shrink-0 text-ink-gray-5"
						aria-hidden="true"
					/>
				</button>
			</template>
			<div
				class="w-80 max-w-[calc(100vw-2rem)] rounded-6 border border-outline-gray-2 bg-surface-base p-2 shadow-lg"
			>
				<p v-if="loading" class="px-2 py-3 text-p-sm text-ink-gray-5">
					Loading keys…
				</p>
				<Alert
					v-else-if="error"
					theme="red"
					title="Couldn't load SSH keys"
					:description="error"
					:primary-action="{ label: 'Retry', onClick: reload }"
				/>
				<p v-else-if="!keys.length" class="px-2 py-3 text-p-sm text-ink-gray-5">
					No team keys yet.
				</p>
				<div v-else class="max-h-56 overflow-y-auto">
					<label
						v-for="key in keys"
						:key="key.name"
						class="flex cursor-pointer items-center gap-3 rounded-4 px-2 py-2 hover:bg-surface-gray-2"
					>
						<input
							type="checkbox"
							:checked="modelValue.includes(key.name)"
							class="size-4"
							@change="toggle(key.name)"
						/>
						<span class="min-w-0">
							<span class="block truncate text-p-sm font-medium text-ink-gray-8"
								>{{ key.title }}</span
							>
							<span class="block truncate font-mono text-xs text-ink-gray-5"
								>{{ key.fingerprint }}</span
							>
						</span>
					</label>
				</div>
				<div
					v-if="canManageSSHKeys"
					class="border-t border-outline-gray-1 pt-2"
				>
					<Button
						label="Add SSH key"
						icon-left="lucide-plus"
						variant="ghost"
						size="sm"
						@click="adding = true; open = false"
					/>
				</div>
			</div>
		</Popover>
		<p v-if="required && !modelValue.length" class="text-p-sm text-ink-gray-5">
			Select at least one key to sign in to Ubuntu.
		</p>
		<SSHKeyDialog v-model="adding" :save="create" @saved="saved" />
	</div>
</template>
