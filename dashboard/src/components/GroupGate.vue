<script setup>
import { computed } from 'vue'
import { LoadingText } from 'frappe-ui'
import NoAccess from '@/components/NoAccess.vue'
import { useCapabilities } from '@/composables/useCapabilities'

// Gate a whole sidebar group at the shell: while caps load show a skeleton; if
// the gate fails, the group resolves to one no-access page (don't mount the
// child routes the API would 403). Gate either on a single `capability`, or on
// `requireMember` (any capability on the active team = belongs to it).
const props = defineProps({
  capability: { type: String, default: '' },
  requireMember: { type: Boolean, default: false },
  roles: { type: String, default: 'Owner or Billing' },
})

const { caps, has, isMember } = useCapabilities()
const allowed = computed(() =>
  props.requireMember ? isMember.value : has(props.capability),
)
const loading = computed(() => caps.loading && !caps.data)
</script>

<template>
  <div v-if="loading" class="space-y-3 p-5">
    <LoadingText :lines="5" />
  </div>
  <NoAccess v-else-if="!allowed" :roles="roles" />
  <router-view v-else />
</template>
