<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed } from 'vue'
import { useAppMenu } from '@/composables/useAppMenu'
import { useCapabilities } from '@/composables/useCapabilities'
import { useSession } from '@/composables/useSession'
import {
	openSettings,
	SETTINGS_TABS,
	type SettingsTabDef,
} from '@/composables/useSettings'

// Mobile's settings hub: the same tabs the desktop dialog lists in its sidebar,
// in the same two sections, as rows that push a page. Sign out stays here at the
// bottom — it ends the session rather than settling into a tab.
const { activeTeamLabel } = useSession()
const { isMember, canEditTeam, canDeleteTeam } = useCapabilities()
const { currentUser, logoutAndRedirect } = useAppMenu()

const groups = computed(() => {
	const available = SETTINGS_TABS.filter((tab) => {
		if (tab.requires === 'member') return isMember.value
		if (tab.requires === 'teamAdmin')
			return canEditTeam.value || canDeleteTeam.value
		return true
	}).map((tab) => ({
		tab,
		// A row that can show what it's currently set to, does. It saves a tap
		// for the two things people check without changing.
		current:
			tab.value === 'profile'
				? currentUser.value
				: tab.value === 'teams'
					? activeTeamLabel.value
					: '',
	}))

	const order: SettingsTabDef['group'][] = ['Account', 'Team']
	return order
		.map((group) => ({
			label: group,
			rows: available.filter((row) => row.tab.group === group),
		}))
		.filter((group) => group.rows.length > 0)
})
</script>

<template>
	<div class="m-2 space-y-4">
		<section v-for="group in groups" :key="group.label">
			<p class="px-1 pb-1.5 text-xs text-ink-gray-5">{{ group.label }}</p>
			<div class="divide-y divide-outline-gray-1 rounded border">
				<Button
					v-for="row in group.rows"
					:key="row.tab.value"
					variant="ghost"
					class="w-full !justify-between text-base"
					size="lg"
					@click="openSettings(row.tab.value)"
				>
					{{ row.tab.label }}
					<template #suffix>
						<span
							class="flex min-w-0 items-center gap-1 text-p-sm text-ink-gray-5"
						>
							<span class="truncate">{{ row.current }}</span>
							<span class="lucide-chevron-right size-4 shrink-0" />
						</span>
					</template>
				</Button>
			</div>
		</section>

		<div class="rounded border">
			<Button
				theme="red"
				variant="ghost"
				class="!h-auto w-full !justify-start !rounded-none !px-4 !py-3"
				@click="logoutAndRedirect"
			>
				Sign out
			</Button>
		</div>
	</div>
</template>
