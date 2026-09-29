import { API, download } from '@/api/methods'

/** Download the statutory PDF of one invoice. */
export function downloadInvoice(name: string): void {
	window.open(download(API.invoicePdf, { name }), '_blank')
}
