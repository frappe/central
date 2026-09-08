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

// What's yours and what the team's are different kinds of setting, so they get
// their own sections rather than one long list.
const groups = computed(() => {
	const order: SettingsTabDef['group'][] = ['Account', 'Administration']
	return order
		.map((group) => ({
			label: group,
			items: tabs.value.filter((tab) => tab.group === group),
		}))
		.filter((group) => group.items.length > 0)
})

// Losing a tab you can no longer reach shouldn't leave an empty content pane.
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
		<SettingsSidebar class="dark:bg-surface-elevation-1">
			<SettingsNavGroup
				v-for="group in groups"
				:key="group.label"
				:label="group.label"
			>
				<SettingsNavItem
					v-for="tab in group.items"
					:key="tab.value"
					:value="tab.value"
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
				<SettingsHeader :title="tab.title" :description="tab.description" />
				<SettingsBody>
					<component :is="tab.component" />
				</SettingsBody>
			</SettingsPanel>
		</SettingsContent>
	</SettingsDialog>
</template>
