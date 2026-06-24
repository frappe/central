import { toast } from 'frappe-ui'

// Thin wrapper over frappe-ui's global toast (rendered by <ToastProvider/> in
// AppShell). `errorToast` digs the human message out of a Frappe error response.

export function successToast(message: string): void {
  toast.success(message)
}

export function infoToast(message: string): void {
  toast.info(message)
}

interface FrappeError {
  messages?: string[]
  exc_message?: string
  message?: string
}

export function errorToast(e: unknown, fallback = 'Something went wrong.'): void {
  if (isAbortError(e)) return
  toast.error(getErrorMessage(e, fallback))
}

// A fetch aborted because it was superseded (e.g. an in-flight list request when
// the active team switches) rejects with a DOMException named 'AbortError'. It's
// not a real failure — callers should ignore it rather than surface it.
export function isAbortError(e: unknown): boolean {
  if (!e || typeof e !== 'object') return false

  const err = e as { name?: string; message?: string }
  return err.name === 'AbortError'
}

export function getErrorMessage(e: unknown, fallback = 'Something went wrong.'): string {
  const err = (e ?? {}) as FrappeError
  const msg =
    err.messages?.[0] ||
    err.exc_message ||
    err.message ||
    (typeof e === 'string' ? e : fallback)
  return stripHtml(msg)
}

function stripHtml(s: string): string {
  return String(s).replace(/<[^>]*>/g, '')
}
