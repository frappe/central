<script setup lang="ts">
import { Button } from 'frappe-ui'
import { useSession } from '@/composables/useSession'

const { impersonatedTeam, endImpersonation } = useSession()
</script>

<template>
	<div
		v-if="impersonatedTeam"
		role="status"
		class="flex shrink-0 items-center justify-between gap-3 border-b border-outline-amber-2 bg-surface-amber-2 px-4 py-1.5"
	>
		<p class="min-w-0 text-p-sm text-ink-amber-8">
			You are viewing
			<span class="text-p-sm-semibold">{{ impersonatedTeam.label }}</span>
			as its owner. Your changes apply to this team.
		</p>
		<Button size="sm" label="Exit" @click="endImpersonation" />
	</div>
</template>
