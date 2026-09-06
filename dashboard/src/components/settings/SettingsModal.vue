<script setup lang="ts">
import {
	Avatar,
	SettingsBody,
	SettingsContent,
	SettingsDialog,
	SettingsHeader,
	SettingsNavGroup,
	SettingsNavItem,
	SettingsPanel,
	SettingsSidebar,
} from 'frappe-ui'
import { computed, watch } from 'vue'
import { useCapabilities } from '@/composables/useCapabilities'
import { useMyProfile } from '@/composables/useMyProfile'
import {
	SETTINGS_TABS,
	type SettingsTabDef,
	settingsOpen,
	settingsTab,
} from '@/composables/useSettings'

// Desktop's settings surface: every tab in one dialog, so nothing is a dead end
// — you can fix your photo, switch teams and rename one without closing
// anything. Mobile renders the same tabs as pages (see SettingsDetailPage).
const { profile } = useMyProfile()
const { isMember, canEditTeam, canDeleteTeam } = useCapabilities()

const tabs = computed(() =>
	SETTINGS_TABS.filter((tab) => {
		if (tab.requires === 'member') return isMember.value
		if (tab.requires === 'teamAdmin')
			return canEditTeam.value || canDeleteTeam.value
		return true
	}),
)

// What's yours and what's the team's are different kinds of setting, so they
// get their own sections rather than one long list.
const groups = computed(() => {
	const order: SettingsTabDef['group'][] = ['Account', 'Team']
	return order
		.map((group) => ({
			label: group,
			items: tabs.value.filter((tab) => tab.group === group),
		}))
		.filter((group) => group.items.length > 0)
})

// Switching to a team you don't administer drops the Team settings tab. If that
// was the open one, land somewhere real instead of an empty content pane.
watch(tabs, (available) => {
	if (!available.some((tab) => tab.value === settingsTab.value)) {
		settingsTab.value = available[0]?.value ?? 'profile'
	}
})
</script>

<template>
	<!-- `v-model:open`, not a bare `v-model`: SettingsDialog names its open model
	     (`defineModel('open')`) and declares no `modelValue`, so a bare v-model
	     binds a prop nothing reads and the dialog never opens. -->
	<SettingsDialog v-model:open="settingsOpen" v-model:tab="settingsTab">
		<SettingsSidebar>
			<SettingsNavGroup v-for="group in groups" :key="group.label">
				<template #label>
					<span class="text-p-sm text-ink-gray-5">{{ group.label }}</span>
				</template>

				<SettingsNavItem
					v-for="tab in group.items"
					:key="tab.value"
					:value="tab.value"
					class="!text-p-sm"
				>
					<template #prefix>
						<!-- Your own face on your own tab; everything else takes an icon. -->
						<Avatar
							v-if="tab.value === 'profile'"
							:image="profile?.user_image ?? undefined"
							:label="profile?.full_name || profile?.user || ''"
							size="xs"
						/>
						<span v-else :class="`${tab.icon} size-4 text-ink-gray-7`" />
					</template>
					{{ tab.label }}
				</SettingsNavItem>
			</SettingsNavGroup>
		</SettingsSidebar>

		<SettingsContent class="bg-surface-base">
			<SettingsPanel v-for="tab in tabs" :key="tab.value" :value="tab.value">
				<SettingsHeader class="!px-10 !pt-8">
					<h2 class="text-lg-semibold text-ink-gray-8">{{ tab.title }}</h2>
					<p
						v-if="tab.description"
						class="mt-1 max-w-md text-p-base text-ink-gray-6"
					>
						{{ tab.description }}
					</p>
				</SettingsHeader>
				<SettingsBody viewport-class="px-10 pb-8 pt-6">
					<component :is="tab.component" />
				</SettingsBody>
			</SettingsPanel>
		</SettingsContent>
	</SettingsDialog>
</template>

<style scoped>
:deep(.text-base.leading-5.text-ink-gray-6) {
	@apply text-p-sm;
}
</style>
