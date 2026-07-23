<script setup lang="ts">
import { ref, watch } from 'vue'
import { Button, Switch, toast } from 'frappe-ui'
import PageHeader from '@/components/common/PageHeader.vue'
import { useNotificationPreferences } from '@/composables/useNotificationPreferences'
import type { NotificationPreference } from '@/composables/useNotificationPreferences'

const { preferences, loading, saving, save } = useNotificationPreferences()

const local = ref<NotificationPreference[]>([])
watch(preferences, (p) => {
	local.value = p.map((r) => ({ ...r }))
}, { immediate: true })

const dirty = ref(false)
watch(local, () => { dirty.value = true }, { deep: true })

function toggle(category: string, field: 'email_enabled' | 'in_app_enabled') {
	const row = local.value.find((r) => r.category === category)
	if (row) row[field] = !row[field]
}

async function onSave() {
	try {
		await save(local.value)
		dirty.value = false
		toast.success('Preferences saved')
	} catch (e: unknown) {
		toast.error(e instanceof Error ? e.message : 'Failed to save')
	}
}
</script>

<template>
	<div class="flex h-full flex-col">
		<PageHeader title="Notification preferences">
			<template #actions>
				<Button
					variant="solid"
					label="Save"
					:loading="saving"
					:disabled="!dirty"
					@click="onSave"
				/>
			</template>
		</PageHeader>

		<div class="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6">
			<div class="mx-auto max-w-2xl space-y-4">
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
			</div>
		</div>
	</div>
</template>
