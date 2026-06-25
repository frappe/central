<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
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
const touched = ref(false)
const initialValue = props.modelValue
const error = computed(() =>
  touched.value || props.submitted ? props.validator(props.modelValue) : '',
)

const dirty = computed(() => props.modelValue !== initialValue)
const valid = computed(() => !props.validator(props.modelValue))

function validate(): boolean {
  touched.value = true
  return valid.value
}

defineExpose({ dirty, valid, validate })
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
    @blur="touched = true"
  >
    <template v-for="name in Object.keys($slots)" :key="name" #[name]="slotProps">
      <slot :name="name" v-bind="slotProps" />
    </template>
  </FormControl>
</template>
