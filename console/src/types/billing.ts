// Response/row shapes for the billing dashboard endpoints
// (central.billing.api.dashboard.*). The backend serializes money as MAJOR-unit
// numbers plus an ISO `currency` (ADR 0003 keeps minor units server-side only),
// so every amount here is a major-unit `number` the UI formats but never maths on.

export type Currency = string

/** get_team_overview — the team billing header. */
export interface TeamOverview {
  team: string
  tier: string | null
  max_spend: number
  standing: string
  resources: number
  clusters: number
  currency: Currency
}

/** One projected/charged line on the forecast or an invoice. Shaped by the
 *  server's `_describe_line`: `item` is the human title, `detail` spells out what
 *  drove the charge. Currency lives on the parent (forecast/invoice), not the row. */
export interface BillingLine {
  item: string
  detail?: string | null
  kind?: 'Plan' | 'Overage' | (string & {})
  resource_type?: string | null
  plan?: string | null
  subscription_resource?: string | null
  days?: number | null
  hours?: number | null
  quantity?: number
  rate?: number
  unit?: string | null
  amount: number
}

/** get_forecast — current-cycle projection vs wallet. */
export interface Forecast {
  period_start: string
  period_end: string
  projected_total: number
  subtotal: number
  tax_amount: number
  tax_type: string | null
  credit_balance: number
  shortfall: number
  days_remaining: number
  currency: Currency
  credit_alert: boolean
  line_items: BillingLine[]
}

/** One rung of the trust-tier ladder (customer-facing: Spending Limits). */
export interface TierLevel {
  tier: string
  sequence: number
  max_spend: number | null
  max_resource_count: number | null
  min_paid_invoices: number | null
  min_cumulative_paid: number | null
}

/** get_trust_tier — current rung, next rung, and the full ladder (`all_levels`). */
export interface TrustTier {
  team: string
  currency: Currency
  current: TierLevel | null
  next: TierLevel | null
  is_top_tier: boolean
  progress: {
    resources_used: number
    paid_invoices: number
    cumulative_paid: number
  }
  all_levels: (TierLevel | null)[]
}

/** get_credit_balance — wallet balance. */
export interface CreditBalance {
  balance: number
  currency: Currency
}

/** credit_ledger row — append-only wallet movement (ADR 0006). */
export interface CreditLedgerEntry {
  entry_type: 'Credit' | 'Debit'
  amount: number
  running_balance: number
  currency: Currency
  note: string | null
  created_at: string | null
  reference_type: string | null
  reference_name: string | null
}

export type InvoiceStatus = 'Draft' | 'Unpaid' | 'Paid' | 'Overdue' | 'Void' | (string & {})

/** list_invoices row — summary only. */
export interface InvoiceSummary {
  name: string
  period_start: string
  period_end: string
  status: InvoiceStatus
  invoice_type: string
  total: number
  amount_paid: number
  currency: Currency
  due_date: string | null
}

/** One event in an invoice's lifecycle timeline (issued → credits → payment → settled). */
export interface InvoiceActivity {
  at: string | null
  kind: 'issued' | 'credit' | 'payment' | 'paid'
  title: string
  detail: string | null
  amount: number
  currency: Currency
  theme: 'gray' | 'blue' | 'green' | 'red' | 'orange'
}

/** get_invoice — one invoice with line items, tax block, and activity. */
export interface InvoiceDetail {
  name: string
  team: string
  status: InvoiceStatus
  invoice_type: string
  period_start: string
  period_end: string
  currency: Currency
  subtotal: number
  output_tax_type: string | null
  output_tax_rate: number | null
  output_tax_amount: number
  zero_rating_reason: string | null
  total: number
  credit_applied: number
  expected_collection: number
  amount_paid: number
  due_date: string | null
  /** A charge is in flight (or captured, awaiting the settlement webhook). */
  payment_in_progress: boolean
  items: BillingLine[]
  activity: InvoiceActivity[]
}

/** list_subscriptions row — per-server plan. */
export interface SubscriptionRow {
  name: string
  /** Friendly server name (Asset.title), e.g. "atlas-web-01". */
  server: string | null
  /** Asset gateway URL for the "Open server" action. */
  gateway_url: string | null
  plan: string
  /** Human plan name (Plan.title), e.g. "Business". */
  plan_title: string | null
  cluster: string | null
  /** Human region label, e.g. "Mumbai, India (AWS)". */
  region: string | null
  billing_cycle: string
  account_standing: string
  /** The VM's operational state (Running/Stopped/Paused/Terminated/…) from the Asset. */
  status: string | null
  /** 0 when billing is paused. */
  enabled: boolean | number
  /** Resolved monthly price for the team's currency + region. */
  monthly_rate: number | null
  currency: string
}

export type PaymentMethodType = 'Card' | 'UPI Autopay' | (string & {})

/** list_payment_methods row — display fields only; gateway secrets never returned. */
export interface PaymentMethod {
  name: string
  method_type: PaymentMethodType
  status: string
  display_label: string | null
  is_default: boolean | number
  priority: number
  reauth_required: boolean | number
  expiry_month: number | null
  expiry_year: number | null
}

/** get_payment_method_options — what the team may add, resolved from its currency. */
export interface PaymentMethodOptions {
  gateway: string | null
  adapter_key: 'Stripe' | 'Razorpay' | (string & {})
  currency: Currency
  methods: PaymentMethodType[]
  allow_upi: boolean
  upi_block_reason: string | null
  upi_limit: number | null
  /** Stripe only — publishable key for Elements; never the secret key. */
  publishable_key?: string | null
}

/** get_billing_profile — stored profile fields plus the derived setup state the
 *  dashboard gates on. Extra stored fields (gstin, address, …) ride along. */
export interface BillingProfile {
  team: string
  currency?: Currency
  legal_name?: string | null
  email?: string | null
  phone?: string | null
  gstin?: string | null
  address_line1?: string | null
  address_line2?: string | null
  city?: string | null
  state?: string | null
  country?: string | null
  pincode?: string | null
  // Derived (the gate fields):
  complete: boolean
  missing: string[]
  currency_locked: boolean
  supported_currencies: Currency[]
}

/** get_billing_geo — dropdown feeds for the address form. */
export interface BillingGeo {
  countries: string[]
  india_states: { value: string; label: string }[]
}

/** get_billing_settings — alert thresholds. */
export interface BillingSettings {
  team: string
  min_balance: number
  spend_alert_threshold: number
}

/** get_collection_status — collection mode + the "Action Required" banner feed (ADR 0005). */
export interface CollectionStatus {
  mode?: string
  collection_mode?: string
  action_required: boolean
  reason: string | null
  threshold: number | null
  projected_total: number
  wallet_balance: number
  shortfall: number
  currency: Currency
}

export type NotificationCategory = 'Billing' | 'Server' | 'Team'
export type NotificationSeverity = 'Info' | 'Success' | 'Warning' | 'Error'

/** A Team Notification — one item in the console's unified in-app feed. */
export interface TeamNotification {
  name: string
  category: NotificationCategory
  event_type: string | null
  severity: NotificationSeverity
  title: string
  message: string | null
  reference_doctype: string | null
  reference_name: string | null
  action_label: string | null
  action_route: string | null
  is_read: 0 | 1
  read_at: string | null
  creation: string
}

/** list_notifications response — items plus the live unread count. */
export interface NotificationFeed {
  items: TeamNotification[]
  unread: number
}

/** get_notification_preferences — per-event-type delivery toggles (0/1), keyed by event. */
export interface NotificationPreferences {
  team: string
  [event: string]: number | string
}
