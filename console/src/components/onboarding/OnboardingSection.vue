<script setup lang="ts">
import { computed } from 'vue'

// One accordion section of the onboarding wizard. Purely presentational: the
// parent decides the `state` (complete | active | locked) and whether it's `open`;
// this renders the header (status circle, title, status label, chevron) and a
// collapsible body. The body always stays mounted so the step inside can report
// its completion — it's just height-collapsed when closed.

type SectionState = 'complete' | 'active' | 'locked'

const props = withDefaults(
  defineProps<{
    index: number
    title: string
    description?: string
    optional?: boolean
    state?: SectionState
    open?: boolean
  }>(),
  { description: '', optional: false, state: 'locked', open: false },
)

defineEmits<{ toggle: [] }>()

const circleClass = computed(
  () =>
    ({
      complete: 'border-outline-gray-3 text-ink-green-3',
      active: 'border-outline-gray-4 text-ink-gray-9',
      locked: 'border-outline-gray-2 text-ink-gray-4',
    })[props.state],
)

const statusLabel = computed(() => {
  if (props.state === 'complete') return 'Completed'
  if (props.state === 'locked') return 'Locked'
  return props.optional ? 'Optional' : 'Required'
})
const statusClass = computed(() =>
  props.state === 'complete' ? 'text-ink-green-3' : 'text-ink-gray-5',
)
</script>

<template>
  <section
    class="overflow-hidden rounded-lg border transition-colors"
    :class="
      state === 'active'
        ? 'border-outline-gray-3 bg-surface-white shadow-sm'
        : 'border-outline-gray-1 bg-surface-gray-1'
    "
  >
    <button
      type="button"
      class="flex w-full items-center gap-3 px-4 py-3.5 text-left transition-colors"
      :class="state === 'locked' ? 'cursor-not-allowed' : 'hover:bg-surface-gray-2'"
      :disabled="state === 'locked'"
      @click="$emit('toggle')"
    >
      <span
        class="flex size-7 shrink-0 items-center justify-center rounded-full border text-p-sm transition-colors"
        :class="circleClass"
      >
        <span v-if="state === 'complete'" class="lucide-check size-4" aria-hidden="true" />
        <span v-else-if="state === 'locked'" class="lucide-lock size-3.5" aria-hidden="true" />
        <template v-else>{{ index + 1 }}</template>
      </span>

      <div class="min-w-0 flex-1">
        <span class="text-base text-ink-gray-9">{{ title }}</span>
        <p class="mt-0.5 truncate text-p-sm text-ink-gray-5">{{ description }}</p>
      </div>

      <span class="shrink-0 text-p-sm" :class="statusClass">{{ statusLabel }}</span>
      <span
        v-if="state !== 'locked'"
        class="lucide-chevron-down size-4 shrink-0 text-ink-gray-5 transition-transform duration-200"
        :class="open && 'rotate-180'"
        aria-hidden="true"
      />
    </button>

    <!-- Collapsible body. The 0fr→1fr grid trick animates height without
         measuring; the inner div clips the content while collapsed. -->
    <div
      class="grid transition-[grid-template-rows] duration-200 ease-out"
      :class="open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'"
    >
      <div class="overflow-hidden">
        <div class="border-t border-outline-gray-1 px-4 py-4">
          <slot />
        </div>
      </div>
    </div>
  </section>
</template>
