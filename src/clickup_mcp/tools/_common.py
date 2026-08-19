from .._json import error_envelope

NO_TOKEN = error_envelope(
    "not_configured", "No ClickUp API token. Send the X-Clickup-Token header.", False
)
