<script setup lang="ts">
import { ref, watch } from 'vue'
import SidePanel from '@/components/common/SidePanel.vue'
import CapabilityList from '@/components/team/CapabilityList.vue'
import { useTeamRoles } from '@/composables/useTeamRoles'
import { roleDisplay } from '@/lib/roles'
import type { TeamRoleRow } from '@/types/api'

// A role's capabilities, docked beside the page content and teleported into the
// Access page's flex row. Opened from a role row on the Roles tab, or a member's
// role badge on the Team tab.
const role = defineModel<TeamRoleRow | null>('role', { default: null })
const { capabilities } = useTeamRoles()

// The Teleport stays mounted so SidePanel can play its slide-out; `shown` holds
// the last role so the body doesn't blank halfway through that animation.
const shown = ref<TeamRoleRow | null>(null)
watch(role, (value) => {
	if (value) shown.value = value
})
</script>

<template>
	<Teleport defer to="#team-page-aside">
		<SidePanel
			:open="!!role"
			:title="shown?.role_name"
			:subtitle="shown ? roleDisplay(shown).description : ''"
			@update:open="(v: boolean) => !v && (role = null)"
		>
			<div v-if="shown" class="p-4">
				<CapabilityList :caps="shown.capabilities" :palette="capabilities" />
			</div>
		</SidePanel>
	</Teleport>
</template>
