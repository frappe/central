<script setup lang="ts">
import { useSession } from '@/composables/useSession'

const { activeTeamLabel, activePartner } = useSession()
</script>

<template>
	<div
		v-if="activePartner"
		class="flex shrink-0 items-center gap-2 border-b border-outline-gray-1 bg-surface-gray-2 px-4 py-1.5"
		role="status"
	>
		<span
			class="lucide-handshake size-4 shrink-0 text-ink-gray-5"
			aria-hidden="true"
		/>
		<p class="truncate text-p-sm text-ink-gray-7">
			Working on {{ activeTeamLabel }} as {{ activePartner }}
		</p>
	</div>
</template>
