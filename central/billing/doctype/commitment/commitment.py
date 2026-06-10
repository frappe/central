# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Team-level commitment: a fixed-bundle spend floor held for a term.

The discount lives on the invoice (computed at generation, see commitments.py);
this document only records the contract. Clawback on breach is issue #31.
"""

from frappe.model.document import Document


class Commitment(Document):
	pass
