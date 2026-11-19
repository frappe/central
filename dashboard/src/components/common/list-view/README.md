# Central ListView

`ListView` is Central's standard table. It wraps the frappe-ui `List` from `frappe-ui/list` with search, filters, sorting, pagination, and the loading, error, empty, and no-results states.

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
  { key: 'name', label: 'Name', sortable: true },
  { key: 'status', label: 'Status', width: '8rem' },
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

Each column `key` names its cell slot, so `<template #status="{ row, value }">` renders the Status cell. Without a slot, the cell shows the value as text. `value` sets what the cell shows and what search, filters and sorting read. It defaults to `row[key]`. `compare` sorts by something other than the value. `width` is a grid track such as `minmax(0,2fr)` or `6rem`, and defaults to `minmax(0,1fr)`. `class` goes on the header cell and every body cell, such as `max-md:hidden`. A filter's `key` is the column whose value it matches.

Listen to `@row-click` to make rows clickable; it emits the row. A clickable row cannot contain buttons, so a button stretches over the row instead. Give a control in a clickable row the `relative` class to put it above that button. `RowActionsMenu` already does this.

When rows are selected, the `#selection-actions` slot replaces the search and filter controls, and the toolbar stays, so the table does not move. The footer shows the row count only from 5 rows, because a shorter list is counted at a glance. Size a column by its content: `size` is a share of the free width, so give the main column the largest share and keep short values, such as a date or a badge, narrow.

Set `:show-page-size="false"` to hide the 10/20/50 choice when the page owns the page size. Set the size with `createListViewQuery({ pageSize })`.

For DocTypes, pair `server-side` with `useFrappeList`. It translates the same
query object into Desk's permission-aware `frappe.desk.reportview.get_list` and
`get_count` calls. Without `server-side`, `ListView` applies the query to the
provided rows in the browser.

Call `list.listenForUpdates()` from component setup to subscribe to Frappe's
DocType room. It coalesces committed `list_update` events and reloads both rows
and count, matching Desk list-view invalidation without coupling the visual
component to Frappe.
