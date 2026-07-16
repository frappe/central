# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

"""India GST state codes — the single source of truth shared by the Billing
Profile validation, the Desk form, and the dashboard.

A GSTIN's first two digits are the registration state's code, so this map lets us
(a) offer a state dropdown when the billing country is India and (b) check that a
saved GSTIN's state code matches the chosen state.
"""

INDIA = "India"

# State / UT name -> 2-digit GST state code (per the GST state code list).
GST_STATE_CODES = {
	"Jammu and Kashmir": "01",
	"Himachal Pradesh": "02",
	"Punjab": "03",
	"Chandigarh": "04",
	"Uttarakhand": "05",
	"Haryana": "06",
	"Delhi": "07",
	"Rajasthan": "08",
	"Uttar Pradesh": "09",
	"Bihar": "10",
	"Sikkim": "11",
	"Arunachal Pradesh": "12",
	"Nagaland": "13",
	"Manipur": "14",
	"Mizoram": "15",
	"Tripura": "16",
	"Meghalaya": "17",
	"Assam": "18",
	"West Bengal": "19",
	"Jharkhand": "20",
	"Odisha": "21",
	"Chhattisgarh": "22",
	"Madhya Pradesh": "23",
	"Gujarat": "24",
	"Dadra and Nagar Haveli and Daman and Diu": "26",
	"Maharashtra": "27",
	"Karnataka": "29",
	"Goa": "30",
	"Lakshadweep Islands": "31",
	"Kerala": "32",
	"Tamil Nadu": "33",
	"Puducherry": "34",
	"Andaman and Nicobar Islands": "35",
	"Telangana": "36",
	"Andhra Pradesh": "37",
	"Ladakh": "38",
	"Other Territory": "97",
}


def india_state_options() -> list[str]:
	"""State names for the billing-profile state dropdown (India)."""
	return list(GST_STATE_CODES)


def state_code(state: str | None) -> str | None:
	"""The 2-digit GST code for an Indian state, or None if unrecognised."""
	return GST_STATE_CODES.get((state or "").strip())


