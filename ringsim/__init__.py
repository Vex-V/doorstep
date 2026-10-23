"""A Ring Partner API simulator: a day of videos, each at a time of day, served
over HTTP in the Partner API's shapes, with signed webhooks pushed to an app.

    python -m ringsim scenarios/demo/scenario.json --webhook http://127.0.0.1:8000/ring/webhook

An app points its Ring base URL at the simulator (`http://127.0.0.1:8100`) and
makes the same calls it makes against `https://api.amazonvision.com`: devices,
Event History, clip and snapshot download (through a 303 to a pre-signed-style
URL, as Ring does), Chime configurations and playback. Webhooks are signed with
HMAC-SHA256 over the raw body, retried six times, and carry Ring's payload v1.1.

What the Developer Playground cannot do and this can: doorbell presses,
webhooks, a Chime, several cameras, and your own footage, added from its page.
The day plays on schedule (faster than real time, so "still there after two
hours" takes minutes), one video after another, or by hand.

It imports nothing from Doorstep: any Ring app can point at it.
"""

__version__ = "0.1.0"
