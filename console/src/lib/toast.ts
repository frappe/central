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
  const err = (e ?? {}) as FrappeError
  const msg =
    err.messages?.[0] ||
    err.exc_message ||
    err.message ||
    (typeof e === 'string' ? e : fallback)
  toast.error(stripHtml(msg))
}

function stripHtml(s: string): string {
  return String(s).replace(/<[^>]*>/g, '')
}
