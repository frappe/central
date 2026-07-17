import { computed, ref, watch, type Ref } from 'vue'
import { useSession } from '@/composables/useSession'

export function useTeamRowSelection<T>(
	rows: Ref<T[]>,
	rowKey: (row: T) => string,
) {
	const { activeTeam } = useSession()
	const selectedKey = ref<string | null>(null)

	const selected = computed(
		() => rows.value.find((row) => rowKey(row) === selectedKey.value) ?? null,
	)

	watch([rows, activeTeam], () => {
		if (
			selectedKey.value &&
			!rows.value.some((row) => rowKey(row) === selectedKey.value)
		) {
			selectedKey.value = null
		}
	})

	function select(row: T): void {
		selectedKey.value = rowKey(row)
	}

	function clear(): void {
		selectedKey.value = null
	}

	return { selectedKey, selected, select, clear }
}
