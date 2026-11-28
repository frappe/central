<script setup lang="ts">
import { Button, FormLabel } from 'frappe-ui'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'
import { __ } from '@/lib/translate'

interface AffiliateLinkBoxProps {
	link: string
	label: string
}

const props = defineProps<AffiliateLinkBoxProps>()

async function copy(): Promise<void> {
	if (await copyToClipboard(props.link)) {
		successToast(__('Link copied'))
		return
	}
	reportError(__('Could not copy the link. Select it and copy it manually.'))
}
</script>

<template>
	<div>
		<FormLabel :label="label" />
		<div
			class="mt-1.5 flex items-center gap-2 rounded-6 bg-surface-gray-1 py-2 ps-4 pe-2"
		>
			<code class="min-w-0 flex-1 truncate font-mono text-sm text-ink-gray-8">
				{{ link }}
			</code>
			<Button
				variant="ghost"
				icon-left="lucide-copy"
				:label="__('Copy')"
				@click="copy"
			/>
		</div>
	</div>
</template>
