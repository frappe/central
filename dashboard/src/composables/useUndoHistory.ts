import { useKeyboardShortcut } from 'frappe-ui'
import { computed, type MaybeRefOrGetter, shallowRef, toValue } from 'vue'

interface UndoEntry<T> {
	snapshot: T
	source: string
	recordedAt: number
}

interface UndoHistoryOptions<T> {
	/** Puts an earlier snapshot back in place of the current state. */
	restore: (snapshot: T) => void
	/** Off while the state is read-only, such as during a save. */
	enabled?: MaybeRefOrGetter<boolean>
}

/**
 * An undo stack for an unsaved draft, with Mod+Z bound to it. Text fields and dialogs keep
 * their own Mod+Z.
 */
export function useUndoHistory<T>(options: UndoHistoryOptions<T>) {
	const entries = shallowRef<UndoEntry<T>[]>([])
	const canUndo = computed(() => entries.value.length > 0)

	/** Save the state as it is before a change. Edits from one `source` in a burst merge. */
	function record(snapshot: T, source = ''): void {
		const now = Date.now()
		const last = entries.value[entries.value.length - 1]
		// Keystrokes in one field arrive as many edits; within a second they are one step.
		if (source && last?.source === source && now - last.recordedAt < 1000) {
			last.recordedAt = now
			return
		}

		entries.value = [...entries.value, { snapshot, source, recordedAt: now }]
	}

	function undo(): void {
		const last = entries.value[entries.value.length - 1]
		if (!last) return

		entries.value = entries.value.slice(0, -1)
		options.restore(last.snapshot)
	}

	function clear(): void {
		entries.value = []
	}

	useKeyboardShortcut({
		combo: 'Mod+Z',
		description: 'Undo',
		group: 'General',
		enabled: () => canUndo.value && toValue(options.enabled ?? true),
		handler: undo,
	})

	return { canUndo, record, undo, clear }
}
