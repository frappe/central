import { toast } from 'frappe-ui'
import { readonly, ref } from 'vue'

export interface ErrorAlertAction {
	label: string
	onClick: () => unknown
}

export interface ErrorAlert {
	id: number
	title: string
	description: string
	action?: ErrorAlertAction
}

interface ReportErrorOptions {
	title?: string
	fallback?: string
	action?: ErrorAlertAction
}

interface FrappeError {
	messages?: string[]
	exc_message?: string
	message?: string
	title?: string
	type?: string
	exc_type?: string
	name?: string
	status?: number
}

const activeError = ref<ErrorAlert | null>(null)
let nextErrorId = 1

export function successToast(message: string): void {
	toast.success(message)
}

export function infoToast(message: string): void {
	toast.info(message)
}

/** Show an actionable failure as a persistent alert. */
export function reportError(
	error: unknown,
	options: ReportErrorOptions = {},
): void {
	if (isAbortError(error)) return
	showErrorAlert({
		title: options.title ?? getErrorTitle(error),
		description: getErrorMessage(error, options.fallback),
		action: options.action,
	})
}

/** Reserve transient error toasts for failures outside the user's current task. */
export function backgroundErrorToast(
	error: unknown,
	fallback = "A background update failed. We'll try again later.",
): void {
	if (isAbortError(error)) return
	toast.error(getErrorMessage(error, fallback))
}

export function useErrorAlert() {
	return {
		error: readonly(activeError),
		dismissError,
	}
}

export function dismissError(id?: number): void {
	if (id && activeError.value?.id !== id) return
	activeError.value = null
}

export function isAbortError(error: unknown): boolean {
	if (!error || typeof error !== 'object') return false

	const value = error as { name?: string; message?: string }
	if (value.name === 'AbortError') return true
	const message = String(value.message ?? '').toLowerCase()
	return message === 'aborted' || message.includes('signal is aborted')
}

export function getErrorMessage(
	error: unknown,
	fallback = "We couldn't complete that. Please try again.",
): string {
	const value = (error ?? {}) as FrappeError
	const message =
		value.messages?.[0] ||
		value.exc_message ||
		value.message ||
		(typeof error === 'string' ? error : fallback)
	return stripErrorType(stripHtml(message), value.type || value.exc_type)
}

export function getErrorTitle(error: unknown): string {
	const value = (error ?? {}) as FrappeError
	const type = `${value.type ?? ''} ${value.exc_type ?? ''} ${value.name ?? ''}`
	const message = `${value.message ?? ''} ${value.messages?.join(' ') ?? ''}`
	const signature = `${type} ${message}`.toLowerCase()
	if (value.status === 403 || signature.includes('permission'))
		return "You don't have access"
	if (value.status === 401 || signature.includes('authentication'))
		return 'Your session has expired'
	if (signature.includes('validation')) return 'Check the details and try again'
	if (signature.includes('rate limit')) return 'Try again in a moment'
	if (
		signature.includes('failed to fetch') ||
		signature.includes('networkerror') ||
		signature.includes('load failed')
	)
		return 'Connection problem'

	const title = stripHtml(value.title ?? '').trim()
	if (title && !['Error', 'Message'].includes(title)) return title
	return "That action couldn't be completed"
}

function showErrorAlert(alert: Omit<ErrorAlert, 'id'>): void {
	activeError.value = { id: nextErrorId++, ...alert }
}

function stripErrorType(message: string, type?: string): string {
	if (!type) return message
	const prefix = `${type}:`
	return message.startsWith(prefix)
		? message.slice(prefix.length).trim()
		: message
}

function stripHtml(value: string): string {
	return String(value).replace(/<[^>]*>/g, '')
}
