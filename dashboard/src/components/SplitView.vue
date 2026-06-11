<script setup>
// List-left / detail-right master–detail. The list grows; the detail is a fixed
// ~480px panel pinned right (border-l), NOT a modal — a modal is reserved for
// actions. On mobile the detail slides over the list full-screen.
//
// `open` (v-model) tracks whether a row is selected, so the parent can clear it.
const open = defineModel('open', { type: Boolean, default: false })
</script>

<template>
  <div class="flex min-h-0 flex-1">
    <!-- List -->
    <div
      class="min-w-0 flex-1 overflow-y-auto"
      :class="open ? 'hidden sm:block' : 'block'"
    >
      <slot name="list" />
    </div>

    <!-- Detail -->
    <aside
      v-if="open"
      class="flex w-full shrink-0 flex-col overflow-y-auto border-outline-gray-1 sm:w-[480px] sm:border-l"
    >
      <div class="flex items-center justify-between border-b border-outline-gray-1 px-4 py-3 sm:hidden">
        <button class="text-p-sm text-ink-gray-6" @click="open = false">← Back</button>
      </div>
      <slot name="detail" />
    </aside>
  </div>
</template>
