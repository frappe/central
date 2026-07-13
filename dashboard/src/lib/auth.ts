import { frappeRequest } from 'frappe-ui'

export async function postFrappe<T>(
  path: string,
  payload: Record<string, unknown>,
): Promise<T> {
  return frappeRequest({
    url: path,
    method: 'POST',
    params: payload,
  }) as Promise<T>
}

export async function getFrappe<T>(
  path: string,
  params?: Record<string, unknown>,
): Promise<T> {
  return frappeRequest({
    url: path,
    method: 'GET',
    params,
  }) as Promise<T>
}

// Auth + onboarding endpoints call the v1 method route (like sign_up), so callers
// build the URL with this prefix and a dotted method path from `API`.
export function methodUrl(path: string): string {
  return `/api/method/${path}`
}

export function emailError(value: string): string {
  if (!value.trim()) return 'Email is required.'
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())) return 'Enter a valid email.'
  return ''
}

export function requiredError(label: string) {
  return (value: string): string => (value.trim() ? '' : `${label} is required.`)
}

export function frappeErrorMessage(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback
  const messages = (error as Error & { messages?: unknown[] }).messages
  const message = messages?.find((item): item is string => typeof item === 'string' && Boolean(item))
  return message || error.message || fallback
}
