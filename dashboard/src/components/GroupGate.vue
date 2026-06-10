<script setup>
import { computed } from 'vue'
import { LoadingText } from 'frappe-ui'
import NoAccess from '@/components/NoAccess.vue'
import { useCapabilities } from '@/composables/useCapabilities'

// Gate a whole sidebar group at the shell: while caps load show a skeleton;
// if the view capability is absent, the group resolves to one no-access page
// (don't mount the child routes the API would 403).
const props = defineProps({
  capability: { type: String, required: true },
  roles: { type: String, default: 'Owner or Billing' },
})

const { caps, has } = useCapabilities()
const allowed = computed(() => has(props.capability))
const loading = computed(() => caps.loading && !caps.data)
</script>

<template>
  <div v-if="loading" class="space-y-3 p-5">
    <LoadingText :lines="5" />
  </div>
  <NoAccess v-else-if="!allowed" :roles="roles" />
  <router-view v-else />
</template>
