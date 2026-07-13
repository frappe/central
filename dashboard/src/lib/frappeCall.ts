// frappe-ui's useCall resolves even on server error — it never rejects the
// promise, it just sets `.error`. Mutation composables need a throwing submit
// so a single try/catch covers both the toast and the `busy` cleanup.
export async function submitOrThrow<TParams extends object>(
  call: { submit: (params: TParams) => Promise<unknown>; error: unknown },
  params: TParams,
): Promise<void> {
  await call.submit(params)
  if (call.error) throw call.error
}
