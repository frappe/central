from __future__ import annotations

import io

import frappe
from frappe import _

# Formats an avatar/logo may be. Raster only — an SVG could carry scripts into
# every console page that renders it. MPO is what iPhones call some JPEGs.
_IMAGE_EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "MPO": "jpg", "WEBP": "webp", "GIF": "gif"}


def read_image_upload(upload, max_bytes: int, basename: str) -> tuple[bytes, str]:
	"""Validate an uploaded image by its actual bytes and return
	`(content, file_name)`.

	The client's Content-Type and filename are never trusted: the type comes
	from sniffing the pixels (Pillow), and the stored name is `basename` plus
	the extension the sniffed format dictates. Otherwise a script file declared
	as `image/png` but named `evil.html` would be saved verbatim and served
	back as HTML from the public /files route.
	"""
	content = upload.stream.read()
	if len(content) > max_bytes:
		frappe.throw(_("Keep the image under 2 MB."), frappe.ValidationError)

	try:
		from PIL import Image

		with Image.open(io.BytesIO(content)) as image:
			image_format = image.format
			image.verify()  # catches truncated/corrupt files
	except Exception:
		image_format = None
	if image_format not in _IMAGE_EXTENSIONS:
		frappe.throw(_("Use a PNG, JPEG, WebP, or GIF image."), frappe.ValidationError)

	return content, f"{basename}.{_IMAGE_EXTENSIONS[image_format]}"
