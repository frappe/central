<script setup lang="ts">
import { BottomSheet, PageHeaderMobileTitle } from 'frappe-ui'
import { ref } from 'vue'
import Sidebar from '@/components/navigation/Sidebar.vue'

// On mobile the header's title doubles as the section switcher. The bottom bar
// only holds four tabs, so everything else the drawer lists — Servers, Services,
// Team, the billing pages — would otherwise cost a trip back to Home. Home
// itself doesn't use this: that page already *is* the list.
//
// The sheet lives here rather than in the shell so it unmounts with the page,
// which is also what dismisses it once you've picked somewhere to go.
defineProps<{ title: string }>()

const open = ref(false)
</script>

<template>
	<!-- PageHeaderMobileTitle, not a bare button: the header's <h1> clamps with
	     -webkit-line-clamp, which counts line boxes — an inline-flex child is one
	     atomic box, so a long title would never clamp and would instead grow past
	     the 52px header and get hard-clipped. This carries the min-w-0/truncate
	     that makes it ellipsise instead. -->
	<PageHeaderMobileTitle>
		<button
			class="inline-flex min-w-0 items-center gap-1"
			aria-haspopup="dialog"
			:aria-expanded="open"
			@click="open = true"
		>
			<span class="truncate">{{ title }}</span>
			<span
				class="lucide-chevron-down size-4 shrink-0 text-ink-gray-5"
				aria-hidden="true"
			/>
		</button>
	</PageHeaderMobileTitle>

	<!-- Named so it doesn't announce as the generic "Bottom sheet". -->
	<BottomSheet v-model:open="open" title="Go to">
		<Sidebar is-mobile class="p-4" />
	</BottomSheet>
</template>
