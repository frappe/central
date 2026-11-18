<script setup lang="ts">
import { Tooltip } from 'frappe-ui'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'

interface CopyableValueProps {
	value: string
	/** Names the value in the accessible label and the toast, such as "IPv6 address". */
	label: string
	/** A block shows the value in a full-width box, for a command. */
	block?: boolean
}

defineOptions({ inheritAttrs: false })

const props = defineProps<CopyableValueProps>()

async function copy(): Promise<void> {
	if (await copyToClipboard(props.value)) {
		successToast(`${props.label} copied`)
		return
	}
	reportError(
		`Could not copy the ${props.label.toLowerCase()}. Select it and copy it manually.`,
	)
}
</script>

<template>
	<Tooltip :text="`Click to copy the ${label.toLowerCase()}`" :hover-delay="0">
		<button
			v-bind="$attrs"
			type="button"
			class="min-w-0 cursor-pointer break-all rounded-4 text-left font-mono text-ink-gray-9 hover:bg-surface-gray-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-outline-gray-3"
			:class="
				block
					? 'w-full bg-surface-gray-2 px-3 py-2 text-p-sm hover:bg-surface-gray-3'
					: '-mx-1 px-1 text-sm'
			"
			:aria-label="`Copy ${label.toLowerCase()} ${value}`"
			@click="copy"
		>
			{{ value }}
		</button>
	</Tooltip>
</template>
