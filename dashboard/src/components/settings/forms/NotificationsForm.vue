<script setup lang="ts">
import {
	Alert,
	Badge,
	Button,
	Select,
	SettingsRow,
	Skeleton,
	Switch,
	TimePicker,
	useCall,
} from 'frappe-ui'
import { computed, reactive, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import EmptyState from '@/components/common/EmptyState.vue'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { getErrorMessage, successToast } from '@/lib/feedback'
import { submitOrThrow } from '@/lib/frappeCall'
import type {
	NotificationCategory as Category,
	NotificationFrequency,
	NotificationPreference as Preference,
	UserNotificationPreferences,
} from '@/types/billing'

// Per-user notification preferences, one row per category. Email delivery and the
// in-app feed toggle independently. Opt-out model: a category with no saved row is
// enabled for both (see the notification engine and the feed's in_app filter), so
// every switch defaults to on and we only persist the user's explicit choices.
interface Channels {
	email: boolean
	in_app: boolean
	frequency: NotificationFrequency
	muted: string[]
}

const CATEGORIES: { key: Category; label: string; hint: string }[] = [
	{
		key: 'Billing',
		label: 'Billing',
		hint: 'Payments, invoices, credit balance and mandates.',
	},
	{
		key: 'Server',
		label: 'Servers',
		hint: 'Server lifecycle, resizes and health.',
	},
	{
		key: 'Team',
		label: 'Team',
		hint: 'Invitations, role changes and membership.',
	},
	{
		key: 'Trial',
		label: 'Trial',
		hint: 'When a free trial ends, stops and is deleted.',
	},
]

const FREQUENCIES = [
	{ label: 'Instantly', value: 'Instant' },
	{ label: 'Daily digest', value: 'Daily' },
	{ label: 'Weekly digest', value: 'Weekly' },
]

const formatHour = (hour: number) => `${String(hour).padStart(2, '0')}:00`

function defaults(): Record<Category, Channels> {
	const channels = () => ({
		email: true,
		in_app: true,
		frequency: 'Instant' as NotificationFrequency,
		muted: [],
	})
	return {
		Billing: channels(),
		Server: channels(),
		Team: channels(),
		Trial: channels(),
	}
}

// Saved rows overlaid on opt-out defaults.
function toMap(prefs: Preference[] | undefined): Record<Category, Channels> {
	const map = defaults()
	for (const p of prefs ?? []) {
		if (map[p.category]) {
			map[p.category] = {
				email: Boolean(Number(p.email_enabled)),
				in_app: Boolean(Number(p.in_app_enabled)),
				frequency: p.frequency,
				muted: p.events
					.filter((event) => !event.email_enabled)
					.map((event) => event.event_type),
			}
		}
	}
	return map
}

const state = reactive<Record<Category, Channels>>(defaults())
const digestHour = ref<number | null>(null)
const formError = ref('')
const expanded = ref<Category | null>(null)
watch(state, () => (formError.value = ''), { deep: true })
watch(digestHour, () => (formError.value = ''))

const load = useCall<UserNotificationPreferences, { team: string }>({
	url: method(API.notificationPreferences),
	params: teamParams,
	immediate: false,
	refetch: true,
})
whenTeamReady(() => load.reload())

watch(
	() => load.data,
	(data) => {
		const map = toMap(data?.preferences)
		Object.assign(state, map)
		digestHour.value = data?.digest_hour ?? null
	},
	{ immediate: true },
)

const save = useCall<
	{ saved: boolean },
	{ team: string; preferences: Preference[]; digest_hour?: number }
>({
	url: method(API.saveNotificationPreferences),
	method: 'POST',
	immediate: false,
})

const dirty = computed(
	() =>
		JSON.stringify(toMap(load.data?.preferences)) !== JSON.stringify(state) ||
		digestHour.value !== load.data?.digest_hour,
)

const digestTime = computed(() =>
	digestHour.value == null ? '' : formatHour(digestHour.value),
)
const usesDigest = computed(() =>
	CATEGORIES.some(
		({ key }) => state[key].email && state[key].frequency !== 'Instant',
	),
)

function eventsOf(category: Category) {
	return load.data?.catalog.find((c) => c.category === category)?.events ?? []
}

function toggleEvent(category: Category, eventType: string, on: boolean) {
	const muted = state[category].muted.filter((name) => name !== eventType)
	state[category].muted = on ? muted : [...muted, eventType]
}

function setDigestHour(value: string) {
	const hour = Number.parseInt(value, 10)
	if (Number.isInteger(hour) && hour >= 0 && hour <= 23) {
		digestHour.value = hour
	}
}

async function onSave(): Promise<void> {
	try {
		const preferences: Preference[] = CATEGORIES.map(({ key }) => ({
			category: key,
			email_enabled: state[key].email ? 1 : 0,
			in_app_enabled: state[key].in_app ? 1 : 0,
			frequency: state[key].frequency,
			events: state[key].muted
				.filter((name) =>
					eventsOf(key).some((event) => event.event_type === name),
				)
				.map((event_type) => ({ event_type, email_enabled: 0 })),
		}))
		await submitOrThrow(save, {
			...teamParams(),
			preferences,
			digest_hour: digestHour.value ?? undefined,
		})
		await load.reload()
		successToast('Notification preferences saved')
	} catch (e) {
		formError.value = getErrorMessage(
			e,
			"Notification preferences couldn't be saved.",
		)
	}
}
</script>

<template>
	<div class="mt-6">
		<Alert v-if="formError" class="mb-4" theme="red" :title="formError" />
		<EmptyState
			v-if="load.error"
			icon="lucide-cloud-off"
			title="Notification settings couldn't load"
			:description="getErrorMessage(load.error, 'Try again in a moment.')"
		>
			<template #action>
				<Button label="Retry" @click="load.reload()" />
			</template>
		</EmptyState>
		<div v-else-if="!load.data" class="space-y-2">
			<Skeleton v-for="n in 4" :key="n" class="h-14 rounded-6" />
		</div>
		<template v-else>
			<!-- Column headers, aligned to the switch cells below: with two switches
			     per row, naming the channel once beats repeating a label against
			     every toggle. -->
			<div
				class="flex items-center justify-end gap-6 pb-1 text-p-sm text-ink-gray-5"
			>
				<span class="w-12 text-center">Email</span>
				<span class="w-12 text-center">In-app</span>
			</div>

			<div
				class="divide-y divide-outline-gray-1 border-t border-outline-gray-1"
			>
				<div v-for="cat in CATEGORIES" :key="cat.key">
					<SettingsRow :title="cat.label" :description="cat.hint">
						<div class="flex items-center gap-6">
							<span class="flex w-12 justify-center">
								<Switch
									v-model="state[cat.key].email"
									:aria-label="`Email notifications for ${cat.label}`"
								/>
							</span>
							<span class="flex w-12 justify-center">
								<Switch
									v-model="state[cat.key].in_app"
									:aria-label="`In-app notifications for ${cat.label}`"
								/>
							</span>
						</div>
					</SettingsRow>

					<div
						v-if="state[cat.key].email"
						class="flex flex-wrap items-center gap-2 pb-4"
					>
						<Select
							v-model="state[cat.key].frequency"
							class="w-40"
							:options="FREQUENCIES"
							:aria-label="`Email frequency for ${cat.label}`"
						/>
						<Button
							v-if="eventsOf(cat.key).length"
							class="ml-auto"
							variant="ghost"
							:label="
								expanded === cat.key
									? 'Hide events'
									: 'Choose events'
							"
							:aria-expanded="expanded === cat.key"
							@click="
								expanded = expanded === cat.key ? null : cat.key
							"
						/>
					</div>

					<ul
						v-if="state[cat.key].email && expanded === cat.key"
						class="mb-4 rounded-6 bg-surface-gray-1 px-3 py-1.5"
					>
						<li
							v-for="event in eventsOf(cat.key)"
							:key="event.event_type"
							class="flex items-center gap-2 py-1.5 text-p-sm text-ink-gray-8"
						>
							<span class="flex-1">{{ event.title }}</span>
							<Badge
								v-if="event.is_critical"
								theme="gray"
								label="Always sent"
							/>
							<Switch
								:model-value="
									Boolean(event.is_critical) ||
									!state[cat.key].muted.includes(event.event_type)
								"
								:disabled="
									Boolean(event.is_critical) ||
									!event.can_receive
								"
								:aria-label="`Email for ${event.title}`"
								@update:model-value="
									toggleEvent(cat.key, event.event_type, $event)
								"
							/>
						</li>
					</ul>
				</div>
				<SettingsRow
					v-if="usesDigest"
					title="Digest time"
					:description="`Daily and weekly digests go out at this hour, ${load.data?.time_zone}. Weekly digests go out on Monday.`"
				>
					<TimePicker
						class="w-28"
						:model-value="digestTime"
						:interval="60"
						:typeable="false"
						aria-label="Digest time"
						@update:model-value="setDigestHour"
					/>
				</SettingsRow>
			</div>

			<p class="mt-3 text-p-sm text-ink-gray-5">
				Critical events, such as a failed payment or a server that is down, are
				always emailed, even when a category's email is off.
			</p>

			<div class="mt-4 flex justify-end">
				<Button
					variant="solid"
					label="Save preferences"
					:loading="save.loading"
					:disabled="!dirty"
					@click="onSave"
				/>
			</div>
		</template>
	</div>
</template>
