<script setup>
import { ref, watch } from 'vue'
import { TextInput, TabButtons } from 'frappe-ui'

// Standard list toolbar: debounced search (left) + status TabButtons (right).
// The search updates `search` (v-model) after a 250ms idle so we don't refilter
// on every keystroke. `tabs` is [{label, value}]; `status` is v-model.
const props = defineProps({
  tabs: { type: Array, default: () => [] },
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
    <TabButtons v-if="tabs.length" v-model="status" :buttons="tabs" />
  </div>
</template>
