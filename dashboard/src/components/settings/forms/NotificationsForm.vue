<script setup lang="ts">
import { Button, SettingsRow, Switch, useCall } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'
import { API, method } from '@/api/methods'
import { teamParams } from '@/composables/useTeamScope'
import { errorToast, successToast } from '@/lib/toast'

// Per-user notification preferences, one row per category. Email delivery and the
// in-app feed toggle independently. Opt-out model: a category with no saved row is
// enabled for both (see engine._email_enabled and the feed's in_app filter), so
// every switch defaults to on and we only persist the user's explicit choices.
type Category = 'Billing' | 'Server' | 'Team'
type Channels = { email: boolean; in_app: boolean }

interface Preference {
	category: Category
	email_enabled: boolean | number
	in_app_enabled: boolean | number
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
]

function defaults(): Record<Category, Channels> {
	return {
		Billing: { email: true, in_app: true },
		Server: { email: true, in_app: true },
		Team: { email: true, in_app: true },
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
			}
		}
	}
	return map
}

const state = reactive<Record<Category, Channels>>(defaults())

const load = useCall<{ preferences: Preference[] }, { team: string }>({
	url: method(API.notificationPreferences),
	params: teamParams,
	immediate: true,
	refetch: true,
})

watch(
	() => load.data,
	(data) => {
		const map = toMap(data?.preferences)
		for (const { key } of CATEGORIES) {
			state[key].email = map[key].email
			state[key].in_app = map[key].in_app
		}
	},
	{ immediate: true },
)

const save = useCall<
	{ saved: boolean },
	{ team: string; preferences: Preference[] }
>({
	url: method(API.saveNotificationPreferences),
	method: 'POST',
	immediate: false,
})

const dirty = computed(() => {
	const loaded = toMap(load.data?.preferences)
	return CATEGORIES.some(
		({ key }) =>
			loaded[key].email !== state[key].email ||
			loaded[key].in_app !== state[key].in_app,
	)
})

async function onSave(): Promise<void> {
	try {
		const preferences: Preference[] = CATEGORIES.map(({ key }) => ({
			category: key,
			email_enabled: state[key].email ? 1 : 0,
			in_app_enabled: state[key].in_app ? 1 : 0,
		}))
		await save.submit({ ...teamParams(), preferences })
		await load.reload()
		successToast('Notification preferences saved')
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<div>
		<!-- Column headers, aligned to the switch cells below: with two switches
		     per row, naming the channel once beats repeating a label against
		     every toggle. -->
		<div
			class="flex items-center justify-end gap-6 pb-1 text-p-sm text-ink-gray-5"
		>
			<span class="w-12 text-center">Email</span>
			<span class="w-12 text-center">In-app</span>
		</div>

		<div class="divide-y divide-outline-gray-1 border-t border-outline-gray-1">
			<!-- label-for="" opts out of SettingsRow's auto-label: it wires the
			     title to the first control it finds, and here that would make
			     clicking "Billing" toggle email only. -->
			<SettingsRow
				v-for="cat in CATEGORIES"
				:key="cat.key"
				:title="cat.label"
				:description="cat.hint"
				label-for=""
			>
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
		</div>

		<div class="mt-4 flex justify-end">
			<Button
				variant="solid"
				label="Save preferences"
				:loading="save.loading"
				:disabled="!dirty"
				@click="onSave"
			/>
		</div>
	</div>
</template>
