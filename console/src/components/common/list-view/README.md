# Central ListView

`ListView` is Central's standard Espresso table. TanStack Table owns sorting,
filtering, pagination, selection, and row identity; this component owns the
markup and the loading, refresh, error, empty, and no-results experiences.

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  createListViewQuery,
  ListView,
  type ListViewColumn,
  type ListViewFilter,
} from '@/components/common/list-view'

interface Project {
  name: string
  status: string
}

const columns = computed<ListViewColumn<Project>[]>(() => [
  { accessorKey: 'name', header: 'Name' },
  { accessorKey: 'status', header: 'Status' },
])

const query = ref(createListViewQuery({ pageSize: 20 }))
const filters: ListViewFilter[] = [
  {
    key: 'status',
    label: 'Status',
    options: ['Active', 'Archived'].map((value) => ({ label: value, value })),
  },
]
</script>

<template>
  <ListView
    v-model:query="query"
    :rows="projects"
    :columns="columns"
    :row-key="(project) => project.name"
    :loading="loading"
    :error="error"
    searchable
    :filters="filters"
    selectable
    @retry="reload"
  >
    <template #empty-action>
      <Button label="New project" />
    </template>
    <template #selection-actions="{ rows }">
      <Button :label="`Archive ${rows.length}`" />
    </template>
  </ListView>
</template>
```

Use TanStack `ColumnDef` options directly for custom cells, sort/filter rules,
and column behavior. `meta.align`, `meta.headerClass`, and `meta.cellClass` are
Central additions for Espresso layout and responsive visibility.

For DocTypes, pair `server-side` with `useFrappeList`. It translates the same
query object into Desk's permission-aware `frappe.desk.reportview.get_list` and
`get_count` calls. Without `server-side`, TanStack applies the query to the
provided rows in the browser.

Call `list.listenForUpdates()` from component setup to subscribe to Frappe's
DocType room. It coalesces committed `list_update` events and reloads both rows
and count, matching Desk list-view invalidation without coupling the visual
component to Frappe.
