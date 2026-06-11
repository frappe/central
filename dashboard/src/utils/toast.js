// One wrapper over frappe-ui's global toast (rendered by FrappeUIProvider in App.vue).
// `errorToast` digs the human message out of a Frappe error response.

import { toast } from 'frappe-ui'

export function successToast(message) {
  toast.success(message)
}

export function infoToast(message) {
  toast.info(message)
}

export function errorToast(e, fallback = 'Something went wrong.') {
  const msg =
    e?.messages?.[0] ||
    e?.exc_message ||
    e?.message ||
    (typeof e === 'string' ? e : fallback)
  toast.error(stripHtml(msg))
}

function stripHtml(s) {
  return String(s).replace(/<[^>]*>/g, '')
}
