"""The old path of `central.api.oauth`: live sites still call `central.api.email_oauth.*`, and providers send the browser to its `callback`."""

from central.api.oauth import callback, get_active_providers, relay_token, start

__all__ = ["callback", "get_active_providers", "relay_token", "start"]
