from __future__ import annotations

import secrets
from contextlib import contextmanager

import frappe
from frappe import _


class EmailCodeError(frappe.ValidationError):
	"""The code is wrong, expired, or locked."""


class EmailCode:
	"""A one-time code that proves the holder reads one mailbox."""

	TTL_SECONDS = 10 * 60
	MAX_ATTEMPTS = 5

	def __init__(self, email: str) -> None:
		self.email = email
		self.cache_key = f"auth:email-code:{email}"

	@property
	def pending(self) -> dict | None:
		return frappe.cache.get_value(self.cache_key, use_local_cache=False)

	def send(self, subject: str, heading: str, full_name: str | None = None) -> None:
		"""Email a fresh code. Failed attempts carry over, so a resend cannot reset the lock."""
		pending = self.pending or {}
		attempts = pending.get("attempts", 0)
		if attempts >= self.MAX_ATTEMPTS:
			self._throw_locked()

		code = f"{secrets.randbelow(900_000) + 100_000}"
		self._store({"code": code, "attempts": attempts, "full_name": full_name or pending.get("full_name")})
		self._mail(code, subject.format(code), heading)

	@contextmanager
	def lock(self):
		"""Hold while a code is checked and spent, so one code signs in once."""
		with frappe.cache.lock(frappe.cache.make_key(f"{self.cache_key}:lock"), timeout=10):
			yield

	def verify(self, code: str) -> dict:
		"""The pending entry for a correct code. A wrong code counts as an attempt."""
		pending = self.pending
		if not pending:
			frappe.throw(_("That code has expired. Request a new code."), EmailCodeError)
		if pending["attempts"] >= self.MAX_ATTEMPTS:
			self._throw_locked()

		if not secrets.compare_digest(pending["code"], code):
			pending["attempts"] += 1
			self._store(pending)
			frappe.throw(_("That code is incorrect. Check your latest email and try again."), EmailCodeError)
		return pending

	def discard(self) -> None:
		frappe.cache.delete_value(self.cache_key)

	def _store(self, pending: dict) -> None:
		frappe.cache.set_value(self.cache_key, pending, expires_in_sec=self.TTL_SECONDS)

	def _mail(self, code: str, subject: str, heading: str) -> None:
		try:
			frappe.sendmail(
				recipients=[self.email],
				subject=subject,
				template="verification_code",
				args={"code": code, "heading": heading, "expires_minutes": self.TTL_SECONDS // 60},
				now=True,
			)
		except Exception:
			frappe.log_error(title="Email code could not be sent")
			# A mail error can queue its own message. The user reads only ours.
			frappe.clear_messages()
			frappe.throw(_("We could not send a code to this email. Check the address and try again."))

	def _throw_locked(self) -> None:
		frappe.throw(
			_("Too many incorrect codes. Wait {0} minutes, then request a new code.").format(
				self.TTL_SECONDS // 60
			),
			EmailCodeError,
		)
