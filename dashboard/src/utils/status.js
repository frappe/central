// Map every status string to a Badge `theme` in one place — never raw color
// classes. The token system handles light/dark. (billing-ui.md "statusTheme".)

function pick(map, value) {
  return map[String(value ?? '').toLowerCase()] ?? 'gray'
}

// Account-standing axis (Central): current / past_due / suspended.
export function standingTheme(s) {
  return pick({ current: 'green', past_due: 'orange', 'past due': 'orange', suspended: 'red' }, s)
}

// Operational axis (Agent): running / stopped / terminated.
export function operationalTheme(s) {
  return pick({ running: 'green', stopped: 'gray', terminated: 'red' }, s)
}

// Invoice status: Paid / Unpaid / Overdue / Void.
export function invoiceTheme(s) {
  return pick(
    { paid: 'green', open: 'orange', unpaid: 'orange', overdue: 'red', void: 'gray', draft: 'gray' },
    s,
  )
}

// Payment attempt / charge result.
export function paymentTheme(s) {
  return pick(
    {
      succeeded: 'green',
      success: 'green',
      paid: 'green',
      failed: 'red',
      'retry scheduled': 'orange',
      scheduled: 'orange',
      pending: 'orange',
      processing: 'blue',
    },
    s,
  )
}

// Cluster-access request status.
export function requestTheme(s) {
  return pick({ pending: 'orange', approved: 'green', declined: 'red' }, s)
}
