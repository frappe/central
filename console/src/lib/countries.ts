import { getFrappe } from '@/lib/auth'

// Country names come from frappe's guest-accessible geo data, so values match
// what the backend knows. The default is guessed from the browser timezone
// (same trick as frappe's setup wizard), falling back to the browser locale.

interface CountryInfo {
  code?: string
  timezones?: string[]
}

export interface CountryOption {
  label: string
  value: string
}

export interface CountryData {
  options: CountryOption[]
  defaultCountry: string
}

let cached: Promise<CountryData> | null = null

export function loadCountryData(): Promise<CountryData> {
  // Don't cache a rejection — a failed fetch would leave the dropdown empty
  // for the whole session. Clear the slot so the next caller retries.
  cached ??= fetchCountryData().catch((error) => {
    cached = null
    throw error
  })
  return cached
}

async function fetchCountryData(): Promise<CountryData> {
  const geo = await getFrappe<{ country_info: Record<string, CountryInfo> }>(
    '/api/method/frappe.geo.country_info.get_country_timezone_info',
  )
  const info = geo?.country_info ?? {}
  return { options: buildOptions(info), defaultCountry: guessCountry(info) }
}

function buildOptions(info: Record<string, CountryInfo>): CountryOption[] {
  return Object.keys(info)
    .map((name) => ({ value: name, label: name }))
    .sort((a, b) => a.value.localeCompare(b.value))
}

function guessCountry(info: Record<string, CountryInfo>): string {
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  for (const [name, data] of Object.entries(info)) {
    if (data.timezones?.includes(timezone)) return name
  }
  return localeCountry(info)
}

function localeCountry(info: Record<string, CountryInfo>): string {
  try {
    const region = new Intl.Locale(navigator.language).maximize().region?.toLowerCase()
    return Object.keys(info).find((name) => info[name].code === region) ?? ''
  } catch {
    return ''
  }
}
