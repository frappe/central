import io
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from central.images import read_image_upload


def png_bytes(color: tuple[int, int, int]) -> bytes:
	"""A real 4×4 PNG. Distinct colors give distinct bytes, so frappe's
	content-hash dedup can't collapse two test uploads into one file."""
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (4, 4), color).save(buf, format="PNG")
	return buf.getvalue()


def jpeg_bytes() -> bytes:
	from PIL import Image

	buf = io.BytesIO()
	Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="JPEG")
	return buf.getvalue()


def upload_stub(content: bytes, filename: str = "evil.html", mimetype: str = "text/html"):
	"""A multipart file part the way werkzeug hands it over. Hostile defaults:
	the validator must not trust either the name or the declared type."""
	return SimpleNamespace(stream=io.BytesIO(content), filename=filename, mimetype=mimetype)


def fake_request(upload) -> SimpleNamespace:
	return SimpleNamespace(files={"file": upload}, method="POST")


class TestReadImageUpload(IntegrationTestCase):
	def test_accepts_real_png_and_names_by_sniffed_format(self):
		# The declared type (text/html) and filename (evil.html) are both
		# hostile — only the pixels decide.
		content, name = read_image_upload(upload_stub(png_bytes((200, 0, 0))), 2**20, "team-logo")
		self.assertEqual(name, "team-logo.png")
		self.assertTrue(content.startswith(b"\x89PNG"))

	def test_accepts_jpeg_as_jpg(self):
		_content, name = read_image_upload(upload_stub(jpeg_bytes()), 2**20, "photo")
		self.assertEqual(name, "photo.jpg")

	def test_rejects_script_bytes_declared_as_image(self):
		# The pre-fix bypass: HTML bytes declared image/png, named .html, would
		# have been stored verbatim and served back as text/html.
		evil = upload_stub(b"<script>alert(1)</script>", "evil.html", "image/png")
		with self.assertRaises(frappe.ValidationError):
			read_image_upload(evil, 2**20, "team-logo")

	def test_rejects_truncated_image(self):
		half = png_bytes((0, 200, 0))
		with self.assertRaises(frappe.ValidationError):
			read_image_upload(upload_stub(half[: len(half) // 2]), 2**20, "team-logo")

	def test_rejects_oversize(self):
		with self.assertRaises(frappe.ValidationError):
			read_image_upload(upload_stub(png_bytes((0, 0, 200))), 16, "team-logo")


class TestSetTeamLogo(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for email in ("logo.owner@example.test", "logo.viewer@example.test"):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": email.split("@", 1)[0],
						"enabled": 1,
						"send_welcome_email": 0,
					}
				).insert()
		self.owner = "logo.owner@example.test"
		self.viewer = "logo.viewer@example.test"
		self.team = frappe.get_doc(
			{
				"doctype": "Team",
				"team_name": "Logo Team",
				"owner_user": self.owner,
				"members": [
					{"user": self.owner, "role": "Owner", "status": "Active"},
					{"user": self.viewer, "role": "Viewer", "status": "Active"},
				],
			}
		).insert()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _set_logo(self, upload):
		from central.api.teams import set_team_logo

		with patch("frappe.request", fake_request(upload)):
			return set_team_logo(team=self.team.name)

	def test_upload_stores_server_named_public_file_and_replaces_old(self):
		frappe.set_user(self.owner)

		first = self._set_logo(upload_stub(png_bytes((255, 0, 0))))
		self.assertRegex(first["team_logo"], r"^/files/team-logo.*\.png$")
		self.assertTrue(
			frappe.db.exists("File", {"attached_to_doctype": "Team", "file_url": first["team_logo"]})
		)

		# A replacement must not leave the old logo's File doc behind.
		second = self._set_logo(upload_stub(png_bytes((0, 0, 255))))
		self.assertNotEqual(second["team_logo"], first["team_logo"])
		self.assertFalse(frappe.db.exists("File", {"file_url": first["team_logo"]}))

	def test_clear_removes_logo_and_file(self):
		frappe.set_user(self.owner)
		set_logo = self._set_logo(upload_stub(png_bytes((0, 255, 0))))

		from central.api.teams import set_team_logo

		# No request in play → no upload → clear.
		cleared = set_team_logo(team=self.team.name)
		self.assertIsNone(cleared["team_logo"])
		self.assertFalse(frappe.db.exists("File", {"file_url": set_logo["team_logo"]}))

	def test_rejects_script_upload(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError):
			self._set_logo(upload_stub(b"<script>alert(1)</script>", "x.html", "image/png"))
		self.assertFalse(frappe.get_doc("Team", self.team.name).team_logo)

	def test_requires_team_edit(self):
		frappe.set_user(self.viewer)
		with self.assertRaises(frappe.PermissionError):
			self._set_logo(upload_stub(png_bytes((9, 9, 9))))
