<template>
  <!-- A few obvious times first, with Custom as the escape hatch that opens a real
       date & time picker. v-model is a local datetime string ('YYYY-MM-DD HH:mm:ss',
       the format DateTimePicker emits) or '' for "now". -->
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap gap-1.5">
      <Button
        v-for="p in presets"
        :key="p.key"
        size="sm"
        :variant="mode === p.key ? 'solid' : 'subtle'"
        :label="p.label"
        @click="pickPreset(p)"
      />
      <Button
        size="sm"
        :variant="mode === 'custom' ? 'solid' : 'subtle'"
        label="Custom…"
        @click="mode = 'custom'"
      />
    </div>

    <!-- Custom reveals the picker; presets confirm their resolved time as a caption. -->
    <DateTimePicker
      v-if="mode === 'custom'"
      class="w-fit"
      input-class="!w-[13rem]"
      :model-value="model"
      placeholder="Pick date & time"
      @update:model-value="(v: string) => (model = v || '')"
    />
    <p v-else-if="model" class="flex items-center gap-1.5 text-p-xs text-ink-gray-5">
      <span class="lucide-clock size-3 shrink-0" />
      {{ resolvedLabel }}
    </p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, DateTimePicker } from 'frappe-ui'

const model = defineModel<string>({ default: '' })

type PresetKey = 'tonight' | 'tomorrow' | 'weekend'
interface Preset {
  key: PresetKey
  label: string
  date: Date
}

// Which chip is active; null = nothing chosen yet.
const mode = ref<PresetKey | 'custom' | null>(null)

function pad(n: number): string {
  return String(n).padStart(2, '0')
}
function toModel(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

// The named times, each resolved to a concrete future datetime. Past options drop
// out (no "Tonight" at 11pm).
const presets = computed<Preset[]>(() => {
  const now = new Date()
  const out: Preset[] = []

  const tonight = new Date(now)
  tonight.setHours(22, 0, 0, 0)
  if (tonight > now) out.push({ key: 'tonight', label: 'Tonight', date: tonight })

  const tomorrow = new Date(now)
  tomorrow.setDate(now.getDate() + 1)
  tomorrow.setHours(9, 0, 0, 0)
  out.push({ key: 'tomorrow', label: 'Tomorrow morning', date: tomorrow })

  const weekend = new Date(now)
  const untilSaturday = (6 - now.getDay() + 7) % 7
  weekend.setHours(9, 0, 0, 0)
  weekend.setDate(now.getDate() + untilSaturday)
  if (weekend <= now) weekend.setDate(weekend.getDate() + 7)
  out.push({ key: 'weekend', label: 'This weekend', date: weekend })

  return out
})

const resolvedLabel = computed(() => {
  if (!model.value) return ''
  const d = new Date(model.value.replace(' ', 'T')) // parses as local time
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
})

function pickPreset(p: Preset): void {
  mode.value = p.key
  model.value = toModel(p.date)
}

// If the parent hands us a value (e.g. an already-scheduled time), reflect it:
// match a preset, else fall to Custom.
watch(
  model,
  (v) => {
    if (!v) {
      if (mode.value !== 'custom') mode.value = null
      return
    }
    const hit = presets.value.find((p) => toModel(p.date) === v)
    mode.value = hit ? hit.key : 'custom'
  },
  { immediate: true },
)
</script>
