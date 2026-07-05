import crmLogo from '@/assets/products/crm.svg'
import erpnextLogo from '@/assets/products/erpnext.svg'
import helpdeskLogo from '@/assets/products/helpdesk.svg'
import hrmsLogo from '@/assets/products/hrms.svg'

export type ProductInfo = { name: string; logo: string }

// Products a ?product= signup can arrive with. The slug is a frontend-only
// concept, so unknown slugs just fall back to the generic onboarding copy.
const PRODUCTS: Record<string, ProductInfo> = {
  erpnext: { name: 'ERPNext', logo: erpnextLogo },
  crm: { name: 'Frappe CRM', logo: crmLogo },
  helpdesk: { name: 'Frappe Helpdesk', logo: helpdeskLogo },
  hrms: { name: 'Frappe HR', logo: hrmsLogo },
}

export function productInfo(slug: string): ProductInfo | null {
  return PRODUCTS[slug.toLowerCase()] ?? null
}
