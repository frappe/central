/** The share of a bill the wallet pays, in whole percent, when the card or UPI is left `shortfall`. */
export function walletCoverPercent(bill: number, shortfall: number): number {
	if (bill <= 0) return 100
	const covered = bill - Math.min(Math.max(shortfall, 0), bill)
	return Math.floor((covered / bill) * 100)
}

/** How far spend before tax has come to the spend limit, which is also before tax, from 0 to 1. No limit is 0. */
export function spendLimitRatio(spendBeforeTax: number, limit: number): number {
	return limit > 0 ? Math.min(1, Math.max(spendBeforeTax, 0) / limit) : 0
}
