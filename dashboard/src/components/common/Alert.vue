<template>
  <!-- A token-only status alert. Two shapes from one component:
       • block  — icon + title + description (multi-line)
       • banner — icon + title with action(s) on the right
       Neutral surface for every theme; colour comes from the solid status icon
       and the ghost action buttons. Per spec: the red (error) theme turns its
       *title* red (the description stays gray); the primary action is tinted the
       icon colour, secondary actions are gray. -->
  <div
    v-if="visible"
    role="alert"
    class="flex gap-2.5 rounded-lg bg-surface-alpha-gray-1 px-4 py-3.5"
    :class="hasBody ? 'items-start' : 'items-center'"
  >
    <slot name="icon">
      <!-- Solid status icon — the glyph is negative space, so it reads through
           on any background. Coloured via currentColor (the theme accent). -->
      <svg
        v-if="icon"
        viewBox="0 0 16 16"
        fill="none"
        class="size-4 shrink-0"
        :class="[accentText, hasBody ? 'mt-0.5' : '']"
        aria-hidden="true"
      >
        <path :d="icon" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" />
      </svg>
    </slot>

    <div class="min-w-0 flex-1">
      <div class="text-base font-medium" :class="titleColor">{{ title }}</div>
      <div v-if="description || $slots.description" class="mt-0.5 text-p-sm text-ink-gray-6">
        <slot name="description">{{ description }}</slot>
      </div>
    </div>

    <div v-if="actions.length || $slots.action || $slots.footer || dismissible" class="-my-1 flex shrink-0 items-center gap-1 self-center">
      <slot name="action" />
      <slot name="footer" />
      <button
        v-for="(a, i) in actions"
        :key="i"
        type="button"
        class="flex items-center gap-1.5 whitespace-nowrap rounded px-2 py-1 text-base font-medium transition-colors hover:bg-surface-gray-3"
        :class="i === 0 ? accentText : 'text-ink-gray-7'"
        @click="a.onClick"
      >
        <span v-if="a.icon" class="size-4" :class="a.icon" />
        {{ a.label }}
      </button>
      <button v-if="dismissible" type="button" aria-label="Dismiss" class="ml-1" @click="dismiss">
        <span class="lucide-x size-4 text-ink-gray-5" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, useSlots } from 'vue'

// Drop-in for frappe-ui's Alert: same theme names, props and slots.
const props = defineProps({
  theme: { type: String, default: '' }, // 'blue' | 'green' | 'yellow' | 'red'
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  variant: { type: String, default: 'subtle' }, // accepted for API parity
  dismissible: { type: Boolean, default: false },
  // One action object, or an array of them — each { label, onClick, icon? }.
  action: { type: [Object, Array], default: null },
})
const visible = defineModel({ default: true })
const emit = defineEmits(['dismiss'])
const slots = useSlots()

function dismiss() {
  visible.value = false
  emit('dismiss')
}

const actions = computed(() =>
  !props.action ? [] : Array.isArray(props.action) ? props.action : [props.action],
)

// Block when there's a description; banner (centred) otherwise.
const hasBody = computed(() => !!(props.description || slots.description))

// Each theme's accent colour, reused for the icon and the primary action.
const accentText = computed(
  () =>
    ({
      blue: 'text-[var(--ink-blue-7)]',
      green: 'text-[var(--ink-green-7)]',
      red: 'text-[var(--ink-red-7)]',
      yellow: 'text-[var(--ink-amber-7)]',
    })[props.theme] || 'text-ink-gray-8',
)

// Solid 16×16 status icons (glyph is a cut-out, so currentColor fills the shape).
const icon = computed(
  () =>
    ({
      blue: 'M8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8C1 4.13401 4.13401 1 8 1ZM8 6.93652C7.72386 6.93652 7.5 7.16038 7.5 7.43652V11.1436C7.50005 11.4197 7.72389 11.6436 8 11.6436C8.27611 11.6436 8.49995 11.4197 8.5 11.1436V7.43652C8.5 7.16038 8.27614 6.93652 8 6.93652ZM8 4C7.51675 4 7.125 4.39175 7.125 4.875C7.125 5.35825 7.51675 5.75 8 5.75C8.48325 5.75 8.875 5.35825 8.875 4.875C8.875 4.39175 8.48325 4 8 4Z',
      green: 'M8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8C1 4.13401 4.13401 1 8 1ZM11.1055 5.28125C10.8924 5.10562 10.5771 5.13567 10.4014 5.34863L6.95215 9.53223L5.61035 7.79883C5.44143 7.58051 5.12757 7.54022 4.90918 7.70898C4.69088 7.8779 4.65061 8.19177 4.81934 8.41016L6.54395 10.6396C6.63696 10.7598 6.77972 10.8306 6.93164 10.833C7.08364 10.8354 7.22849 10.7687 7.3252 10.6514L11.1729 5.98438C11.3481 5.77144 11.3181 5.45689 11.1055 5.28125Z',
      red: 'M8 1C11.866 1 15 4.13401 15 8C15 11.866 11.866 15 8 15C4.13401 15 1 11.866 1 8C1 4.13401 4.13401 1 8 1ZM10.8535 5.14648C10.6583 4.95122 10.3417 4.95122 10.1465 5.14648L8 7.29297L5.85352 5.14648C5.65825 4.95122 5.34175 4.95122 5.14648 5.14648C4.95122 5.34175 4.95122 5.65825 5.14648 5.85352L7.29297 8L5.14648 10.1465C4.95122 10.3417 4.95122 10.6583 5.14648 10.8535C5.34175 11.0488 5.65825 11.0488 5.85352 10.8535L8 8.70703L10.1465 10.8535C10.3417 11.0488 10.6583 11.0488 10.8535 10.8535C11.0488 10.6583 11.0488 10.3417 10.8535 10.1465L8.70703 8L10.8535 5.85352C11.0488 5.65825 11.0488 5.34175 10.8535 5.14648Z',
      yellow:
        'M7.35174 1.97129C7.64143 1.47669 8.35697 1.47669 8.64666 1.97129L15.0519 12.9078C15.3447 13.4077 14.9847 14.0365 14.4055 14.0367H1.59295C1.0138 14.0364 0.653701 13.4077 0.946469 12.9078L7.35174 1.97129ZM7.9992 10.4117C7.51609 10.4118 7.12433 10.8036 7.1242 11.2867C7.1242 11.7699 7.51601 12.1617 7.9992 12.1617C8.48245 12.1617 8.8742 11.77 8.8742 11.2867C8.87408 10.8036 8.48238 10.4117 7.9992 10.4117ZM8.00018 5.50742C7.72411 5.50742 7.5003 5.73139 7.50018 6.00742V9.25742C7.50018 9.53356 7.72404 9.75742 8.00018 9.75742C8.27615 9.75723 8.50018 9.53344 8.50018 9.25742V6.00742C8.50006 5.73151 8.27608 5.50762 8.00018 5.50742Z',
    })[props.theme] || '',
)

// Only the title carries the error colour; the description stays gray.
const titleColor = computed(() => (props.theme === 'red' ? 'text-ink-red-7' : 'text-ink-gray-9'))
</script>
