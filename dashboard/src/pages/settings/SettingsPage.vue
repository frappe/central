<script setup lang="ts">
import { Button, PageHeaderMobile } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAppMenu } from '@/composables/useAppMenu'
import { useCapabilities } from '@/composables/useCapabilities'
import { useIsMobile } from '@/composables/useIsMobile'
import { useSession } from '@/composables/useSession'
import {
	openSettings,
	SETTINGS_BASE,
	SETTINGS_TABS,
	type SettingsTabDef,
} from '@/composables/useSettings'

// Mobile's settings hub: the same tabs the desktop dialog lists in its sidebar,
// in the same two sections, as rows that push a page. Sign out stays here at the
// bottom — it ends the session rather than settling into a tab.
const { activeTeamLabel } = useSession()
const { isMember, canEditTeam, canDeleteTeam } = useCapabilities()
const { currentUser, logoutAndRedirect } = useAppMenu()

// This hub only makes sense at phone width. Arriving here on a wide screen
// (Back into it, a stale link) or widening past the breakpoint while it's open
// both hand over to the dialog's URL — immediate, or arriving would render a
// stack of rows on a desktop and only correct itself on the next resize.
const router = useRouter()
const isMobile = useIsMobile()
watch(
	isMobile,
	(mobile) => {
		if (!mobile) router.replace(`${SETTINGS_BASE}/profile`)
	},
	{ immediate: true },
)

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
	<!-- No desktop PageHeader and no `sm:hidden`: the watcher above hands this
	     route over to the dialog the moment it isn't mobile, so the page never
	     renders at desktop width. -->
	<PageHeaderMobile title="Settings" />

	<!-- Extra top margin so the first group label clears the header rather than
	     sitting right under its border. -->
	<div class="m-2 mt-4 space-y-4">
		<section v-for="group in groups" :key="group.label">
			<p class="px-1 pb-1.5 text-base text-ink-gray-5">{{ group.label }}</p>
			<div
				class="divide-y divide-outline-gray-1 overflow-hidden rounded-4 border"
			>
				<Button
					v-for="row in group.rows"
					:key="row.tab.value"
					variant="ghost"
					class="w-full !justify-between !rounded-none !font-normal"
					size="lg"
					@click="openSettings(row.tab.value)"
				>
					{{ row.tab.label }}
					<template #suffix>
						<span
							class="flex min-w-0 items-center gap-1 text-p-base text-ink-gray-5"
						>
							<span class="truncate">{{ row.current }}</span>
							<span class="lucide-chevron-right size-4 shrink-0" />
						</span>
					</template>
				</Button>
			</div>
		</section>

		<div class="overflow-hidden rounded-4 border">
			<Button
				theme="red"
				variant="ghost"
				size="lg"
				class="w-full !justify-start !rounded-none !font-normal"
				@click="logoutAndRedirect"
			>
				Sign out
			</Button>
		</div>
	</div>
</template>
