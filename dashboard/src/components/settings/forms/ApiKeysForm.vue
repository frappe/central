<script setup lang="ts">
import { Badge, Button, LoadingText, Tooltip } from 'frappe-ui'
import { computed, ref } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import CreateApiKeyDialog from '@/components/settings/CreateApiKeyDialog.vue'
import { useApiKeys } from '@/composables/useApiKeys'
import { useSession } from '@/composables/useSession'
import { formatCalendarDate, formatDateTime, timeAgo } from '@/lib/datetime'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { ApiKey } from '@/types/apiKeys'

const { keys, loading, error, reload, revoke, revoking } = useApiKeys()
const { teams } = useSession()

reload()

const adding = ref(false)
const revokeTarget = ref<ApiKey | null>(null)
const revokeError = ref('')

const teamLabels = computed(
	() => new Map(teams.value.map((team) => [team.name, team.label])),
)

const isExpired = (key: ApiKey): boolean =>
	new Date(key.expires_at).getTime() <= Date.now()

const scopeCount = (key: ApiKey): string => {
	const count = Object.keys(key.scopes).length
	return count === 1 ? __('1 scope') : __('{0} scopes', [count])
}

const expiryText = (key: ApiKey): string =>
	isExpired(key)
		? __('Expired {0}', [formatCalendarDate(key.expires_at)])
		: __('Expires {0}', [formatCalendarDate(key.expires_at)])

const onRevoke = async (key: ApiKey): Promise<void> => {
	revokeError.value = ''
	try {
		await revoke(key.name)
		revokeTarget.value = null
		successToast(__('API key revoked'))
	} catch (e) {
		revokeError.value = getErrorMessage(e, __("Couldn't revoke the key."))
	}
}
</script>

<template>
	<div class="space-y-4 pt-6">
		<Teleport defer to="#settings-actions-api-keys">
			<Button
				v-if="keys.length"
				:label="__('Add')"
				icon-left="lucide-plus"
				@click="adding = true"
			/>
		</Teleport>

		<LoadingText v-if="loading && !keys.length" :lines="3" />

		<EmptyState
			v-else-if="error && !keys.length"
			icon="lucide-cloud-off"
			:title="__('Couldn\'t load your API keys')"
			:description="getErrorMessage(error, __('Try again in a moment.'))"
		>
			<template #action>
				<Button :label="__('Retry')" @click="reload" />
			</template>
		</EmptyState>

		<EmptyState
			v-else-if="!keys.length"
			icon="lucide-key-round"
			:title="__('No API keys yet')"
			:description="__('A key lets a script or an agent act on one team, with the access you choose.')"
		>
			<template #action>
				<Button
					:label="__('Add API key')"
					icon-left="lucide-plus"
					@click="adding = true"
				/>
			</template>
		</EmptyState>

		<div v-else class="rounded-5 border border-outline-gray-1 px-4">
			<ul class="divide-y divide-outline-gray-1">
				<li
					v-for="key in keys"
					:key="key.name"
					class="flex flex-wrap items-center justify-between gap-3 py-3"
				>
					<div class="min-w-0">
						<div class="flex min-w-0 items-center gap-2">
							<span class="truncate text-base-medium text-ink-gray-9">
								{{ key.title }}
							</span>
							<span class="flex items-center gap-1 text-sm text-ink-gray-5">
								<span
									class="lucide-users size-3.5 shrink-0"
									aria-hidden="true"
								/>
								{{ teamLabels.get(key.team) ?? key.team }}
							</span>
							<Badge v-if="isExpired(key)" :label="__('Expired')" />
							<Badge v-else-if="!key.enabled" :label="__('Turned off')" />
						</div>
						<p
							class="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-p-sm text-ink-gray-5"
						>
							<Tooltip
								:text="
									Object.entries(key.scopes)
										.map(([category, access]) => `${category}: ${access}`)
										.join(', ')
								"
							>
								<span>{{ scopeCount(key) }}</span>
							</Tooltip>
							<span aria-hidden="true">·</span>
							<Tooltip
								v-if="key.last_used_at"
								:text="formatDateTime(key.last_used_at)"
							>
								<span class="text-ink-green-6">
									{{ __('Last used {0}', [timeAgo(key.last_used_at)]) }}
								</span>
							</Tooltip>
							<span v-else>{{ __('Never used') }}</span>
							<span aria-hidden="true">·</span>
							<Tooltip :text="formatDateTime(key.expires_at)">
								<span>{{ expiryText(key) }}</span>
							</Tooltip>
						</p>
					</div>

					<div class="flex shrink-0 items-center gap-2">
						<Tooltip
							:text="__('The start of the key. The secret is never shown again.')"
						>
							<span
								class="rounded-4 bg-surface-gray-2 px-2 py-1 font-mono text-sm text-ink-gray-6"
							>
								{{ key.key_prefix }}…
							</span>
						</Tooltip>
						<Button
							theme="red"
							:label="__('Revoke')"
							@click="revokeTarget = key"
						/>
					</div>
				</li>
			</ul>
		</div>

		<CreateApiKeyDialog v-model="adding" />

		<ConfirmDialog
			v-model:target="revokeTarget"
			:title="__('Revoke API key')"
			:confirm-label="__('Revoke')"
			theme="red"
			:loading="revoking"
			:error="revokeError"
			@confirm="onRevoke"
			@after-leave="revokeError = ''"
		>
			<p v-if="revokeTarget" class="text-p-base text-ink-gray-7">
				{{ __('Calls that use {0} fail from now on. You cannot undo this.', [revokeTarget.title]) }}
			</p>
		</ConfirmDialog>
	</div>
</template>
