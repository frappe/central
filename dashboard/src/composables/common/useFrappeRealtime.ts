import {
	getCurrentInstance,
	onScopeDispose,
	readonly,
	ref,
	toValue,
	watch,
	type MaybeRefOrGetter,
	type Ref,
} from 'vue'

type SocketListener = (...args: unknown[]) => void

interface FrappeSocket {
	connected: boolean
	on(event: string, listener: SocketListener): void
	off(event: string, listener: SocketListener): void
	emit(event: string, ...args: unknown[]): void
}

export interface DocumentUpdateEvent {
	doctype: string
	name: string
	modified: string
}

export interface DocumentViewersEvent {
	doctype: string
	docname: string
	users: string[]
}

export interface DocTypeListUpdateEvent {
	doctype: string
	name: string
	user: string
}

interface DocumentEventListenerOptions {
	emitOpenCloseEvents?: boolean
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

export function useFrappeDocumentEventListener(
	doctype: MaybeRefOrGetter<string>,
	docname: MaybeRefOrGetter<string>,
	onUpdate: (event: DocumentUpdateEvent) => void,
	options: DocumentEventListenerOptions = {},
): {
	viewers: Readonly<Ref<readonly string[]>>
	emitDocOpen: () => void
	emitDocClose: () => void
} {
	const socket = useFrappeSocket()
	const viewers = ref<string[]>([])
	const emitOpenCloseEvents = options.emitOpenCloseEvents ?? true

	watch(
		() => [toValue(doctype), toValue(docname)] as const,
		([nextDoctype, nextDocname], _, onCleanup) => {
			viewers.value = []
			if (!nextDoctype || !nextDocname) return

			const subscribe = () =>
				socket.emit('doc_subscribe', nextDoctype, nextDocname)

			socket.on('connect', subscribe)
			if (socket.connected) subscribe()
			if (emitOpenCloseEvents) {
				socket.emit('doc_open', nextDoctype, nextDocname)
			}

			onCleanup(() => {
				socket.emit('doc_unsubscribe', nextDoctype, nextDocname)
				socket.off('connect', subscribe)
				if (emitOpenCloseEvents) {
					socket.emit('doc_close', nextDoctype, nextDocname)
				}
			})
		},
		{ immediate: true },
	)

	useFrappeEventListener<DocumentUpdateEvent>('doc_update', (event) => {
		if (event.doctype === toValue(doctype) && event.name === toValue(docname)) {
			onUpdate(event)
		}
	})

	useFrappeEventListener<DocumentViewersEvent>('doc_viewers', (event) => {
		if (
			event.doctype === toValue(doctype) &&
			event.docname === toValue(docname)
		) {
			viewers.value = event.users
		}
	})

	return {
		viewers: readonly(viewers),
		emitDocOpen: () => emitDocumentEvent(socket, 'doc_open', doctype, docname),
		emitDocClose: () =>
			emitDocumentEvent(socket, 'doc_close', doctype, docname),
	}
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
			'Frappe socket is unavailable. Call this composable inside setup() after installing FrappeUI.',
		)
	}

	return socket
}

function emitDocumentEvent(
	socket: ReturnType<typeof useFrappeSocket>,
	event: 'doc_open' | 'doc_close',
	doctype: MaybeRefOrGetter<string>,
	docname: MaybeRefOrGetter<string>,
): void {
	const currentDoctype = toValue(doctype)
	const currentDocname = toValue(docname)
	if (currentDoctype && currentDocname) {
		socket.emit(event, currentDoctype, currentDocname)
	}
}
