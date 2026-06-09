"""Gateway integration surface.

This package is the **single** integration surface for payment gateways (issue
#24). Core billing never imports a gateway SDK — only the adapters here do
(`stripe_adapter`, `razorpay_adapter`), enforced by
`tests/test_adapter_isolation.py`. Adding a gateway is one `GatewayAdapter`
subclass passing the shared contract suite; there is no legacy `frappe-payments`
path to fall back to.
"""
