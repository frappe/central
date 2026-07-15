<script setup lang="ts">
import { computed } from 'vue'
import { Dropdown } from 'frappe-ui'

// A compact value dropdown over a discrete ladder (vCPU / RAM / Storage), styled as
// a pill — the precise-picking companion to the slider (#84). Rungs past the
// headroom hard stop come through `disabled` and render greyed, like the
// configurator's bounded menus; the current rung carries a check.
interface LadderOption {
	label: string
	value: number
	disabled?: boolean
}
const props = defineProps<{ options: LadderOption[]; selected: number }>()
const emit = defineEmits<{ select: [value: number] }>()

const menu = computed(() =>
	props.options.map((o) => ({
		label: o.label,
		icon: o.value === props.selected ? 'lucide-check' : undefined,
		disabled: o.disabled,
		onClick: () => {
			if (!o.disabled) emit('select', o.value)
		},
	})),
)
const current = computed(
	() => props.options.find((o) => o.value === props.selected)?.label ?? '',
)
</script>

<template>
	<Dropdown :options="menu" align="end">
		<template #trigger>
			<button
				type="button"
				class="flex items-center gap-1.5 rounded-md bg-surface-gray-2 px-3 py-1.5 text-p-sm font-medium text-ink-gray-8 hover:bg-surface-gray-3"
			>
				<span>{{ current }}</span>
				<span
					class="lucide-chevron-down size-3.5 text-ink-gray-5"
					aria-hidden="true"
				/>
			</button>
		</template>
	</Dropdown>
</template>
