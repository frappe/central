<script setup>
import { ref, watch } from 'vue'
import { TextInput, Select } from 'frappe-ui'

// Standard list toolbar: debounced search (left) + a compact status filter
// dropdown (right). A dropdown — not a tab strip — so the filter costs one
// control's width instead of one-per-status, leaving the row to the list.
//
// The search updates `search` (v-model) after a 250ms idle so we don't refilter
// on every keystroke. `statuses` is [{label, value}]; `status` is v-model.
const props = defineProps({
  statuses: { type: Array, default: () => [] },
  placeholder: { type: String, default: 'Search…' },
})
const search = defineModel('search', { type: String, default: '' })
const status = defineModel('status', { type: [String, Number], default: '' })

const raw = ref(search.value)
let timer
watch(raw, (v) => {
  clearTimeout(timer)
  timer = setTimeout(() => (search.value = v), 250)
})
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-outline-gray-1 px-4 py-3">
    <TextInput
      v-model="raw"
      type="text"
      :placeholder="placeholder"
      class="w-full sm:w-64"
    >
      <template #prefix>
        <span class="lucide-search size-4 text-ink-gray-5" />
      </template>
    </TextInput>
    <Select
      v-if="statuses.length"
      v-model="status"
      :options="statuses"
      class="w-full sm:w-36"
    />
  </div>
</template>
