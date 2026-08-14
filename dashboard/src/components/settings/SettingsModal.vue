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
	<SettingsDialog v-model="settingsOpen" v-model:tab="settingsTab">
		<SettingsSidebar>
			<!-- The dialog names itself. aria-hidden because SettingsDialog already
			     renders a screen-reader-only <h1>Settings</h1> — this is the same
			     title made visible, not a second one. -->
			<p
				aria-hidden="true"
				class="px-2 pb-1 pt-1 text-base font-semibold text-ink-gray-8"
			>
				Settings
			</p>

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

		<SettingsContent>
			<SettingsPanel v-for="tab in tabs" :key="tab.value" :value="tab.value">
				<SettingsHeader :title="tab.title" :description="tab.description" />
				<SettingsBody>
					<div class="mt-6">
						<component :is="tab.component" />
					</div>
				</SettingsBody>
			</SettingsPanel>
		</SettingsContent>
	</SettingsDialog>
</template>
