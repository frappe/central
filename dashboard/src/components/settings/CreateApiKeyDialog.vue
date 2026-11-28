<script setup lang="ts">
import { Alert, Button, Dialog, Select, TabButtons, TextInput } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import { useApiKeys } from '@/composables/useApiKeys'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { ApiKeyAccess } from '@/types/apiKeys'

type Preset = 'custom' | 'read' | 'full'
type Level = ApiKeyAccess | 'None'

const open = defineModel<boolean>({ required: true })

const { scopes, expiryDays, creating, create } = useApiKeys()
const { teams, activeTeam } = useSession()

const USAGE_URL = 'https://frappe.github.io/central/developers/api'
const PRESETS = [
	{ label: __('Custom'), value: 'custom' },
	{ label: __('Read only'), value: 'read' },
	{ label: __('Full access'), value: 'full' },
]

const team = ref('')
const title = ref('')
const days = ref('30')
const preset = ref<Preset>('custom')
const levels = ref<Record<string, Level>>({})
const formError = ref('')
const token = ref('')

const teamOptions = computed(() =>
	teams.value
		.filter((option) => option.status === 'Active')
		.map((option) => ({ label: option.label, value: option.name })),
)

const expiryOptions = computed(() =>
	expiryDays.value.map((count) => ({
		label:
			count === 365
				? __('1 year')
				: count === 1
					? __('1 day')
					: __('{0} days', [count]),
		value: String(count),
	})),
)

const levelOptions = (category: string) => [
	{ label: __('None'), value: 'None' },
	...(scopes.value[category] ?? []).map((level) => ({
		label: level === 'Read' ? __('Read') : __('Write'),
		value: level,
	})),
]

// Read only takes each category's Read level; Full access takes its highest level.
const chosen = computed<Record<string, ApiKeyAccess>>(() => {
	const result: Record<string, ApiKeyAccess> = {}
	for (const [category, options] of Object.entries(scopes.value)) {
		const level =
			preset.value === 'custom'
				? levels.value[category]
				: preset.value === 'read'
					? options.find((option) => option === 'Read')
					: options[options.length - 1]
		if (level && level !== 'None') result[category] = level
	}
	return result
})

const canCreate = computed(
	() =>
		!!team.value &&
		!!title.value.trim() &&
		Object.keys(chosen.value).length > 0,
)

watch(open, (isOpen) => {
	if (!isOpen) return
	team.value = activeTeam.value ?? teamOptions.value[0]?.value ?? ''
	title.value = ''
	days.value = '30'
	preset.value = 'custom'
	levels.value = Object.fromEntries(
		Object.keys(scopes.value).map((category) => [category, 'None']),
	)
	formError.value = ''
	token.value = ''
})

const submit = async (): Promise<void> => {
	if (!canCreate.value) return
	formError.value = ''
	try {
		token.value = await create({
			team: team.value,
			title: title.value.trim(),
			expires_in_days: Number(days.value),
			scopes: chosen.value,
		})
	} catch (e) {
		formError.value = getErrorMessage(e, __("Couldn't create the key."))
	}
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="token ? __('API key · {0}', [title]) : __('Add API key')"
		:disable-outside-click-to-close="!!token"
	>
		<template #default>
			<div v-if="token" class="space-y-4">
				<Alert
					theme="amber"
					:title="__('The key is shown only once')"
					:description="__('Copy it somewhere safe. If you lose it, revoke it and create another.')"
				/>
				<CopyableValue :value="token" :label="__('API key')" block />
				<p class="text-p-sm text-ink-gray-6">
					{{ __('Send it with these two headers:') }}
				</p>
				<pre
					class="overflow-x-auto rounded-4 bg-surface-gray-2 px-3 py-2 font-mono text-p-sm text-ink-gray-8"
				>Authorization: token &lt;key&gt;
Frappe-Authorization-Source: API Key</pre>
			</div>

			<form v-else class="space-y-4" @submit.prevent="submit">
				<Select
					v-model="team"
					:label="__('Team')"
					:options="teamOptions"
					:description="__('The key acts only on this team.')"
					required
				/>
				<TextInput
					v-model="title"
					:label="__('Key name')"
					:placeholder="__('e.g. deploy bot')"
					required
				/>
				<Select
					v-model="days"
					:label="__('Expiration')"
					:options="expiryOptions"
					required
				/>

				<div class="space-y-2">
					<p class="text-sm text-ink-gray-7">{{ __('Permissions') }}</p>
					<TabButtons
						v-model="preset"
						:options="PRESETS"
						:aria-label="__('Permissions')"
						class="w-full"
					/>

					<ul
						v-if="preset === 'custom'"
						class="divide-y divide-outline-gray-1 rounded-5 border border-outline-gray-1 px-3"
					>
						<li
							v-for="category in Object.keys(scopes)"
							:key="category"
							class="flex items-center justify-between gap-3 py-2"
						>
							<span class="text-sm text-ink-gray-8">{{ category }}</span>
							<Select
								v-model="levels[category]"
								class="w-28"
								:options="levelOptions(category)"
								:aria-label="__('{0} access', [category])"
							/>
						</li>
					</ul>
					<p v-else-if="preset === 'read'" class="text-p-sm text-ink-gray-6">
						{{ __("Reads the team's servers. It changes nothing.") }}
					</p>
					<Alert
						v-else
						theme="amber"
						:description="__('Acts as you on the team\'s servers and support tickets, within your role. It can\'t open a console, manage members, billing or API keys.')"
					/>
				</div>

				<p v-if="formError" class="text-p-sm text-ink-red-6">{{ formError }}</p>
			</form>
		</template>

		<template #actions>
			<div v-if="token" class="flex items-center justify-between gap-3">
				<a
					:href="USAGE_URL"
					target="_blank"
					rel="noopener"
					class="flex items-center gap-1.5 text-sm text-ink-gray-7 hover:text-ink-gray-9"
				>
					<span
						class="lucide-external-link size-4 shrink-0"
						aria-hidden="true"
					/>
					{{ __('How to use this key') }}
				</a>
				<Button :label="__('Done')" @click="open = false" />
			</div>
			<div v-else class="flex justify-end gap-2">
				<Button :label="__('Cancel')" @click="open = false" />
				<Button
					variant="solid"
					:label="__('Create')"
					:loading="creating"
					:disabled="!canCreate"
					@click="submit"
				/>
			</div>
		</template>
	</Dialog>
</template>
