import http.server
import select
import sys
import time
import urllib.parse
import webbrowser

import typer

from fcloud.errors import LoginError

# Frappe matches redirect URIs exactly, so the port is fixed and registered with the client.
LOOPBACK_PORT = 9876
REDIRECT_URI = f"http://127.0.0.1:{LOOPBACK_PORT}/callback"
WAIT_SECONDS = 300


class CallbackServer(http.server.HTTPServer):
	"""Catches one redirect back from Central's sign-in page."""

	redirect: dict[str, str] | None = None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
	# A browser preconnect that sends nothing must not stall the wait loop.
	timeout = 1

	def do_GET(self) -> None:
		path, _, query = self.path.partition("?")
		if path != "/callback":
			self.send_error(404)
			return

		self.server.redirect = parse_redirect(query)
		result = "Sign-in failed" if "error" in self.server.redirect else "Signed in"
		body = f"{result}. Return to the terminal.".encode()
		self.send_response(200)
		self.send_header("Content-Type", "text/plain; charset=utf-8")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *arguments) -> None:
		pass


def wait_for_redirect(authorize_url: str) -> dict[str, str]:
	"""Open the sign-in page, then wait for its redirect, or for the redirect address pasted from another machine."""
	try:
		server = CallbackServer(("127.0.0.1", LOOPBACK_PORT), CallbackHandler)
	except OSError as error:
		raise LoginError(f"Can't listen on port {LOOPBACK_PORT} for the sign-in redirect: {error.strerror}.")

	typer.echo(f"Sign in to Central in the browser:\n\n  {authorize_url}\n")
	typer.echo("If the browser runs on another machine, paste the address it ends up on here.")
	webbrowser.open(authorize_url)

	sources = [server, sys.stdin] if sys.stdin.isatty() else [server]
	deadline = time.monotonic() + WAIT_SECONDS
	with server:
		while server.redirect is None and time.monotonic() < deadline:
			ready, _, _ = select.select(sources, [], [], 1)
			if server in ready:
				server.handle_request()
			elif ready:
				server.redirect = read_pasted_redirect()

	if server.redirect is None:
		raise LoginError("Timed out waiting for the sign-in.")
	return server.redirect


def read_pasted_redirect() -> dict[str, str] | None:
	redirect = parse_redirect(sys.stdin.readline())
	if "code" in redirect or "error" in redirect:
		return redirect
	typer.echo("That isn't the redirect address. Copy the full address of the page the browser ends up on.")
	return None


def parse_redirect(text: str) -> dict[str, str]:
	"""The parameters of a redirect URL, or of its bare query string."""
	text = text.strip()
	return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(text).query or text))
