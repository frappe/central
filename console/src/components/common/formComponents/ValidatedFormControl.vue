<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import { FormControl } from 'frappe-ui'

defineOptions({ inheritAttrs: false })

type Validator = (value: string) => string
type InputType = 'text' | 'email' | 'password' | 'number' | 'url' | 'tel'

const props = withDefaults(
  defineProps<{
    modelValue: string
    label: string
    type?: InputType
    validator?: Validator
    submitted?: boolean
  }>(),
  {
    type: 'text',
    validator: () => '',
    submitted: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const attrs = useAttrs()
// Errors show only after a submit attempt (live from then on). Showing them on
// blur inserts text above the submit button mid-click, moving it out from under
// the pointer and swallowing the click.
const error = computed(() => (props.submitted ? props.validator(props.modelValue) : ''))
</script>

<template>
  <FormControl
    :model-value="modelValue"
    :label="label"
    :type="type"
    :error="error"
    size="md"
    variant="subtle"
    v-bind="attrs"
    :class="attrs.class"
    @update:model-value="emit('update:modelValue', String($event ?? ''))"
  >
    <template v-for="name in Object.keys($slots)" :key="name" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps" />
    </template>
  </FormControl>
</template>
