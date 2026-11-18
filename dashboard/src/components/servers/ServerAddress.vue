<script setup lang="ts">
import { Tooltip } from 'frappe-ui'
import { computed } from 'vue'
import CopyableValue from '@/components/common/CopyableValue.vue'
import type { ResourceRow } from '@/lib/serverMap'
import { __ } from '@/lib/translate'

interface ServerAddressProps {
	row: ResourceRow
}

const props = defineProps<ServerAddressProps>()

// A server with a site is reached at the site's domain; any other server at its IP.
const siteHost = computed(() =>
	props.row.site?.url ? new URL(props.row.site.url).host : null,
)
</script>

<template>
	<span class="flex min-w-0 items-center gap-1.5">
		<a
			v-if="siteHost"
			:href="row.site!.url!"
			target="_blank"
			rel="noopener"
			class="relative min-w-0 truncate rounded-4 text-sm text-ink-gray-7 hover:text-ink-gray-9 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
			@click.stop
		>
			{{ siteHost }}
		</a>
		<CopyableValue
			v-else-if="row.server?.public_ipv4"
			class="relative"
			:value="row.server.public_ipv4"
			:label="__('IP address')"
		/>
		<span v-else class="truncate text-sm text-ink-gray-4">
			{{ __('No public IP') }}
		</span>
		<Tooltip v-if="row.server?.has_wireguard_access" :text="__('VPN on')">
			<span
				class="lucide-shield-check relative size-3.5 shrink-0 text-ink-blue-5"
				role="img"
				:aria-label="__('VPN on')"
			/>
		</Tooltip>
	</span>
</template>
