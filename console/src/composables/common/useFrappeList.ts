import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import { useCall } from 'frappe-ui'
import { method } from '@/api/methods'
import type { ListViewQuery } from '@/components/common/list-view'
import { useFrappeListInvalidation } from '@/composables/common/useFrappeRealtime'

type FilterValue = string | number | boolean | null
export type FrappeListFilter = [string, string, FilterValue]

interface UseFrappeListOptions<T> {
  doctype: string
  fields: Array<keyof T | string>
  query: MaybeRefOrGetter<ListViewQuery>
  filters?: MaybeRefOrGetter<FrappeListFilter[]>
  searchFields?: string[]
  sortableFields?: string[]
  defaultOrderBy?: string
}

/**
 * Permission-aware server list backed by the same reportview APIs as Desk.
 * ListView owns query state; this composable only translates it to Frappe.
 */
export function useFrappeList<T>(options: UseFrappeListOptions<T>) {
  const criteria = computed(() => {
    const query = toValue(options.query)
    const filters = [...(toValue(options.filters) ?? [])]

    for (const [field, value] of Object.entries(query.filters)) {
      if (value) filters.push([field, '=', value])
    }

    const search = query.search.trim()
    const orFilters: FrappeListFilter[] = search
      ? (options.searchFields ?? []).map((field) => [field, 'like', `%${search}%`])
      : []

    return JSON.stringify({ filters, orFilters })
  })

  const rowsCall = useCall<T[], Record<string, unknown>>({
    url: method('frappe.desk.reportview.get_list'),
    params: () => {
      const query = toValue(options.query)
      const { filters, orFilters } = JSON.parse(criteria.value) as {
        filters: FrappeListFilter[]
        orFilters: FrappeListFilter[]
      }

      return {
        doctype: options.doctype,
        fields: JSON.stringify(options.fields),
        filters: JSON.stringify(filters),
        or_filters: JSON.stringify(orFilters),
        order_by: getOrderBy(query, options),
        start: (query.page - 1) * query.pageSize,
        page_length: query.pageSize,
        view: 'List',
      }
    },
    immediate: false,
    refetch: true,
  })

  const countCall = useCall<number, Record<string, unknown>>({
    url: method('frappe.desk.reportview.get_count'),
    params: () => {
      const { filters, orFilters } = JSON.parse(criteria.value) as {
        filters: FrappeListFilter[]
        orFilters: FrappeListFilter[]
      }

      return {
        doctype: options.doctype,
        filters: JSON.stringify(filters),
        or_filters: JSON.stringify(orFilters),
      }
    },
    immediate: false,
    refetch: true,
  })

  function reload(): void {
    rowsCall.reload()
    countCall.reload()
  }

  function listenForUpdates(): void {
    useFrappeListInvalidation(options.doctype, reload)
  }

  return {
    rows: computed<T[]>(() => rowsCall.data ?? []),
    totalRows: computed(() => countCall.data ?? 0),
    countLoading: computed(() => countCall.loading || !countCall.isFinished),
    loading: computed(() => rowsCall.loading || !rowsCall.isFinished),
    error: computed(() => rowsCall.error || countCall.error),
    reload,
    listenForUpdates,
  }
}

function getOrderBy<T>(
  query: ListViewQuery,
  options: UseFrappeListOptions<T>,
): string {
  const sort = query.sort
  if (sort && options.sortableFields?.includes(sort.key)) {
    return `${sort.key} ${sort.direction}`
  }
  return options.defaultOrderBy ?? 'modified desc'
}
