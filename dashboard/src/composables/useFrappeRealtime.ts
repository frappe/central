import {
	getCurrentInstance,
	type MaybeRefOrGetter,
	onScopeDispose,
	toValue,
	watch,
} from 'vue'

type SocketListener = (...args: unknown[]) => void

interface FrappeSocket {
	connected: boolean
	on(event: string, listener: SocketListener): void
	off(event: string, listener: SocketListener): void
	emit(event: string, ...args: unknown[]): void
}

export interface DocTypeListUpdateEvent {
	doctype: string
	name: string
	user: string
}

export function useFrappeEventListener<T>(
	eventName: MaybeRefOrGetter<string>,
	callback: (event: T) => void,
): void {
	const socket = useFrappeSocket()
	const listener: SocketListener = (event) => callback(event as T)

	watch(
		() => toValue(eventName),
		(event, _, onCleanup) => {
			if (!event) return
			socket.on(event, listener)
			onCleanup(() => socket.off(event, listener))
		},
		{ immediate: true },
	)
}

export function useFrappeDocTypeEventListener(
	doctype: MaybeRefOrGetter<string>,
	onListUpdate: (event: DocTypeListUpdateEvent) => void,
): void {
	const socket = useFrappeSocket()

	watch(
		() => toValue(doctype),
		(nextDoctype, _, onCleanup) => {
			if (!nextDoctype) return

			const subscribe = () => socket.emit('doctype_subscribe', nextDoctype)

			socket.on('connect', subscribe)
			if (socket.connected) subscribe()
			onCleanup(() => {
				socket.emit('doctype_unsubscribe', nextDoctype)
				socket.off('connect', subscribe)
			})
		},
		{ immediate: true },
	)

	useFrappeEventListener<DocTypeListUpdateEvent>('list_update', (event) => {
		if (event.doctype === toValue(doctype)) onListUpdate(event)
	})
}

// One document's room is shared by every consumer listening to it, and leaving is a
// socket-wide act. Counting the consumers keeps one unmounting component from
// unsubscribing the room out from under another that is still listening.
const docRoomConsumers = new Map<string, number>()

/** Listen for one event inside a document's room, re-joining when the document
 *  changes and after a reconnect. Frappe checks read permission on that document
 *  before it lets a client join, so the room is the authorization boundary: only
 *  events for documents this user may read ever reach the browser. */
export function useFrappeDocEventListener<T>(
	doctype: string,
	docname: MaybeRefOrGetter<string | null>,
	eventName: string,
	callback: (event: T) => void,
): void {
	const socket = useFrappeSocket()

	watch(
		() => toValue(docname),
		(name, _, onCleanup) => {
			if (!name) return

			const room = `${doctype}/${name}`
			const subscribe = () => socket.emit('doc_subscribe', doctype, name)
			const consumers = (docRoomConsumers.get(room) ?? 0) + 1
			docRoomConsumers.set(room, consumers)

			socket.on('connect', subscribe)
			if (socket.connected && consumers === 1) subscribe()

			onCleanup(() => {
				socket.off('connect', subscribe)
				const remaining = (docRoomConsumers.get(room) ?? 1) - 1
				if (remaining > 0) {
					docRoomConsumers.set(room, remaining)
					return
				}
				docRoomConsumers.delete(room)
				socket.emit('doc_unsubscribe', doctype, name)
			})
		},
		{ immediate: true },
	)

	useFrappeEventListener<T>(eventName, callback)
}

interface ListInvalidationOptions {
	debounceMs?: number
}

/** Reload a list after Frappe commits a document change, coalescing event bursts.
 *  Pass an array of doctypes to reload one list off several — they share a single
 *  debounce timer, so a change touching more than one still causes exactly one reload. */
export function useFrappeListInvalidation(
	doctype: MaybeRefOrGetter<string> | string[],
	reload: () => unknown,
	options: ListInvalidationOptions = {},
): void {
	const debounceMs = options.debounceMs ?? 150
	let timer: number | undefined
	const schedule = () => {
		window.clearTimeout(timer)
		timer = window.setTimeout(reload, debounceMs)
	}

	const doctypes = Array.isArray(doctype) ? doctype : [doctype]
	for (const dt of doctypes) useFrappeDocTypeEventListener(dt, schedule)

	onScopeDispose(() => window.clearTimeout(timer))
}

function useFrappeSocket(): FrappeSocket {
	const instance = getCurrentInstance()
	const socket = instance?.appContext.config.globalProperties.$socket as
		| FrappeSocket
		| undefined

	if (!socket) {
		throw new Error(
			'Frappe socket is unavailable. Assign app.config.globalProperties.$socket in main.ts.',
		)
	}

	return socket
}
