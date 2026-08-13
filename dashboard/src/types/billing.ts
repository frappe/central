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
	/** Whether the quantity was observed or inferred (projection/basis.py). A stored
	 *  invoice line is always Measured by the time it is issued. */
	basis?: 'Measured' | 'Estimated' | 'Assumed' | (string & {})
	/** The machine this line was billed for — set on plan lines only. */
	server?: string | null
	/** Its technical id (what the Asset is named by), for support and logs. */
	server_id?: string | null
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
	/** Already owed: a locked rate over elapsed days, a landed rollup. */
	measured: number
	/** Inferred, because the period has not happened yet. */
	estimated: number
	/** True when any part of the projection is inferred — the UI must not render a
	 *  bare total when it is. */
	has_estimates: boolean
}

/** get_next_payment — the next debit and anything the team's state says will stop it. */
export interface PaymentBlocker {
	code: string
	title: string
	fix: string | null
}

export interface ChargingMethod {
	label: string | null
	method_type: string | null
	card_network: string | null
	ceiling: number | null
}

export interface NextPayment {
	currency: Currency
	amount: number
	charge_on: string | null
	invoice: string | null
	period_end: string | null
	collection_mode: string | null
	method: ChargingMethod | null
	/** Empty blockers is not a promise of success — only that nothing decides otherwise. */
	will_auto_charge: boolean
	blockers: PaymentBlocker[]
}

export interface PredebitNotice {
	sent_at: string
	invoice: string | null
	subject: string | null
	status: string | null
}

export interface DunningStage {
	date: string
	stage: string
	day: number
}

export interface PaymentSchedule extends NextPayment {
	notices: PredebitNotice[]
	if_unpaid: DunningStage[]
}

/** get_cycle_costs — what the team is paying for this cycle, per subject. */
export interface CycleUsage {
	used: number
	allowance: number
	unit: string | null
	over: boolean
}

export interface CycleCostItem {
	resource_id: string
	title: string
	plan: string | null
	cluster: string | null
	is_service: boolean
	amount: number
	currency: Currency
	usage: CycleUsage | null
}

export interface CycleCosts {
	currency: Currency
	items: CycleCostItem[]
	total: number
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
		first_paid_at: string | null
		last_paid_invoice_amount: number
	}
	all_levels: (TierLevel | null)[]
}

/** get_credit_balance — wallet balance. */
export interface CreditBalance {
	balance: number
	currency: Currency
	/** Promotional credit still on a clock, soonest expiry first. */
	expiring: ExpiringCredit[]
}

/** One promotional grant with time left on it. Purchased credit never expires. */
export interface ExpiringCredit {
	amount: number
	expires_on: string
	ledger_entry: string
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

// Mirrors the Invoice DocType's status Select options — keep in sync with
// central/billing/doctype/invoice/invoice.json.
export type InvoiceStatus =
	| 'Draft'
	| 'Open'
	| 'Paid'
	| 'Overdue'
	| 'Waived'
	| 'Cancelled'

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
	/** The method that settled a Paid invoice (from the capturing attempt). */
	paid_with: { label: string; method_type: string } | null
	items: BillingLine[]
	activity: InvoiceActivity[]
}

/** list_subscriptions row — per-server plan. */
export interface SubscriptionRow {
	name: string
	/** What metering keys on: the Asset for a server, the synthesized subject for a
	 *  team-level service. Joins a row to what it has cost this cycle. */
	resource_id: string | null
	/** Friendly server name (Asset.title), e.g. "atlas-web-01". */
	server: string | null
	/** Asset-backed = a real server; false = a team-level metered service. */
	has_server: boolean
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
	/** Mandate ceiling — what the bank will let us debit in one go. */
	mandate_max_amount?: number | null
	mandate_currency?: string | null
}

/** get_payment_method_options — what the team may add, resolved from its currency. */
/** One tile on a payment surface. The customer picks an instrument and the
 *  instrument picks the gateway (ADR 0023) — we never detect the card network.
 *  Recharge and auto-pay setup return different lists. */
export interface PaymentInstrument {
	instrument:
		| 'Card'
		| 'RuPay Card'
		| 'UPI'
		| 'UPI Autopay'
		| 'Netbanking'
		| (string & {})
	label: string
	description: string
	gateway: string
	adapter_key: 'Stripe' | 'Razorpay' | (string & {})
	/** Which surface offered it: 'recharge' pays once, 'mandate' is saved. */
	surface: 'recharge' | 'mandate' | (string & {})
}

export interface PaymentMethodOptions {
	gateway: string | null
	adapter_key: 'Stripe' | 'Razorpay' | (string & {})
	currency: Currency
	instruments: PaymentInstrument[]
	/** What no tile on this surface can do — e.g. cards no rail will hold a mandate on. */
	note?: string | null
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
	missing_labels?: string[]
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
	/** Networks no rail will auto-charge — shown before the customer picks how to pay. */
	mandate_gap_note?: string | null
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

/** get_spend_history — the period-ranged reads behind Billing → Reports. */
export interface SpendMonth {
	month: string
	label: string
	total: number
	paid: number
	currency: Currency
}

export interface SpendSlice {
	label: string
	amount: number
}

export interface SpendHistory {
	currency: Currency
	from_date: string
	months: SpendMonth[]
	by_product: SpendSlice[]
	by_region: SpendSlice[]
	total: number
	invoice_count: number
}

export interface StatementRow {
	invoice: string
	period_start: string
	period_end: string
	status: InvoiceStatus
	total: number
	tax: number
	credit_applied: number
	amount_paid: number
}

export interface Statement {
	currency: Currency
	from_date: string
	to_date: string
	opening_outstanding: number
	charged: number
	settled_by_credits: number
	settled_by_payment: number
	closing_outstanding: number
	rows: StatementRow[]
}

export interface TaxBucket {
	tax_type: string
	taxable: number
	tax: number
	invoices: number
}

export interface TaxSummary {
	currency: Currency
	from_date: string
	to_date: string
	by_type: TaxBucket[]
	total_tax: number
	total_withheld: number
	/** Central's own rating, not the statutory document (ADR 0019). */
	is_working_paper: boolean
}

export interface RefundRow {
	name: string
	invoice: string | null
	amount: number
	currency: Currency
	destination: 'Source' | 'Wallet' | (string & {})
	status: 'Initiated' | 'Completed' | 'Failed' | (string & {})
	reason: string | null
	/** The provider's refund id — NOT a bank-traceable ARN. */
	gateway_reference: string | null
	created_at: string
	completed_at: string | null
}

/** list_payment_attempts — every charge against the team, across invoices. */
export interface PaymentAttempt {
	name: string
	status: 'Initiated' | 'Authorised' | 'Captured' | 'Failed' | 'Refunded' | (string & {})
	amount: number
	currency: Currency
	gateway: string | null
	invoice: string | null
	failure_code: string | null
	/** The gateway's own wording — kept for quoting to support. */
	failure_reason: string | null
	/** The decline said to the cardholder. Null unless the attempt failed. */
	reason: string | null
	retry_number: number | null
	gateway_transaction_id: string | null
	/** When the payment actually happened — completed, else initiated, else the
	 *  row's own creation. Never render `creation`: for a backfilled attempt that
	 *  is the day it was imported. */
	at: string
	creation: string
}

/** A team-level metered service as the dashboard lists it. */
export interface ServiceRow {
	service_subject: string
	plan: string
	title: string | null
	resource_type: string | null
	cluster: string | null
	currency: string
	unit: string | null
	settlement_mode: string
	allowance: number
	period_usage: number
}

/** One line of "what you're paying for" — a server or a metered service. */
export type PayingForItem =
	| { kind: 'server'; id: string; cost: number | null; sub: SubscriptionRow }
	| { kind: 'service'; id: string; cost: number | null; service: ServiceRow }
