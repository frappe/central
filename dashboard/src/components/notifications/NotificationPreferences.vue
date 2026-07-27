<script setup lang="ts">
import { ref, watch } from 'vue'
import { Switch, toast } from 'frappe-ui'
import { useNotificationPreferences } from '@/composables/useNotificationPreferences'
import type { NotificationPreference } from '@/composables/useNotificationPreferences'

const { preferences, loading, saving, save } = useNotificationPreferences()

const local = ref<NotificationPreference[]>([])
watch(preferences, (p) => {
	local.value = p.map((r) => ({ ...r }))
}, { immediate: true })

function toggle(category: string, field: 'email_enabled' | 'in_app_enabled') {
	const row = local.value.find((r) => r.category === category)
	if (row) row[field] = !row[field]
}

async function onSave() {
	try {
		await save(local.value)
		toast.success('Preferences saved')
	} catch (e: unknown) {
		toast.error(e instanceof Error ? e.message : 'Failed to save')
	}
}
</script>

<template>
	<div class="space-y-4">
		<p class="text-p-sm text-ink-gray-5">
			Control how your team sends you notifications. Changes apply to
			your account only — other team members are not affected.
		</p>

		<div v-if="loading" class="py-10 text-center text-ink-gray-4">
			Loading preferences...
		</div>

		<div v-else class="space-y-3">
			<div
				v-for="pref in local"
				:key="pref.category"
				class="flex items-center justify-between rounded-lg border border-outline-gray-2 bg-surface-elevation-1 px-5 py-4"
			>
				<div class="min-w-0 flex-1">
					<div class="text-base font-medium text-ink-gray-9">
						{{ pref.category }}
					</div>
				</div>
				<div class="flex items-center gap-6">
					<label class="flex items-center gap-2 text-p-sm text-ink-gray-6">
						<Switch
							:model-value="pref.in_app_enabled"
							@click.prevent="toggle(pref.category, 'in_app_enabled')"
						/>
						In-app
					</label>
					<label class="flex items-center gap-2 text-p-sm text-ink-gray-6">
						<Switch
							:model-value="pref.email_enabled"
							@click.prevent="toggle(pref.category, 'email_enabled')"
						/>
						Email
					</label>
				</div>
			</div>
		</div>

		<div class="flex justify-end pt-2">
			<button
				class="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
				:disabled="saving"
				@click="onSave"
			>
				{{ saving ? 'Saving...' : 'Save' }}
			</button>
		</div>
	</div>
</template>
