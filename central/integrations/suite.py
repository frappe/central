from __future__ import annotations

from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
	from central.infrastructure.doctype.mail_service.mail_service import MailService

ADMIN_API = "/api/method/suite.mail.api.admin."
TIMEOUT_SECONDS = (5, 60)
NOT_A_MEMBER = "is not a mail account"


class SuiteClient:
	"""Central's calls to a Suite site's admin API, as the Suite Admin a Mail Service names."""

	def __init__(self, service: MailService):
		self.service = service
		self.headers = {
			"Authorization": f"token {service.api_key}:{service.get_password('api_secret')}",
			"Accept": "application/json",
		}

	def create_send_only_member(self, email: str, password: str) -> None:
		username, domain = email.split("@", 1)
		self.post(
			"add_member",
			{
				"username": username,
				"domain": domain,
				"first_name": username,
				"password": password,
				"backup_email": self.service.backup_email,
				"is_admin": False,
				"send_invite": False,
				# Nobody reads a server's mailbox, so mail sent to it bounces.
				"disable_receiving": True,
			},
		)

	def delete_member(self, email: str) -> None:
		"""Delete the member. A member the site does not have counts as deleted."""
		try:
			self.post("delete_members", {"names": [email]})
		except requests.HTTPError as error:
			# The site refuses an unknown member with the same 403 as a refused caller; only the message differs.
			if NOT_A_MEMBER not in error.response.text:
				raise

	def post(self, method: str, payload: dict) -> None:
		# No redirects: the token must not follow a Location header to another host.
		response = requests.post(
			f"{self.service.site_url.rstrip('/')}{ADMIN_API}{method}",
			json=payload,
			headers=self.headers,
			timeout=TIMEOUT_SECONDS,
			allow_redirects=False,
		)
		response.raise_for_status()
