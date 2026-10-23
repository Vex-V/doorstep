# Friction log: building on the Ring developer platform

Written as it happened, 18–21 October 2026, building Doorstep against the Ring
Partner API and the Developer Playground. Severity: **High** (blocked a
feature, or would break a correct app), **Medium** (cost hours, or needed a
workaround), **Low** (slowed us down).

---

### 1. Playground scenes arrive as `on_demand`, and the type filter is ignored — High

- **Task:** feed Playground events into Doorstep's motion/doorbell pipeline.
- **Steps:** triggered the Package and Motion scenes; called
  `GET /v1/history/devices/{id}/events?event_types=motion,ding`.
- **Expected:** `motion` events (with a `sub_type`), and only the types asked for.
- **Actual:** both scenes appear as `on_demand`, and the filter is ignored:
  every event comes back. An app written to the documented types skips every
  Playground event.
- **Workaround:** filter on our side and treat `on_demand` as motion.
- **Suggestion:** have Playground scenes emit the event types (and sub-types)
  a real device would, and honour `event_types`.

### 2. The Playground sends no webhooks — High

- **Task:** test the webhook receiver (HMAC check, deduplication, the
  5-second answer).
- **Steps:** triggered scenes in the Playground and looked, in the Playground
  and the docs, for a way to receive them as webhooks.
- **Expected:** a signed `motion_detected` webhook per scene.
- **Actual:** the Playground sends none (other teams report the same), so the
  main integration path cannot be exercised against anything Ring runs.
- **Workaround:** poll Event History every 15 s and feed new events in as if
  they were webhooks; for the webhooks themselves, we built our own simulator
  (`ringsim`) that signs them like Ring does.
- **Suggestion:** Playground scenes should fire the app's webhooks, or offer
  a "send test event" button in the portal.

### 3. No doorbell press, and no Chime, in the Playground — High

- **Task:** demonstrate the doorbell (`ding`) path and Chime playback.
- **Steps:** looked for a ding scene; read the device's configuration for
  `audio.customizable_slots`.
- **Expected:** a scene that presses the doorbell; Chime slots to play.
- **Actual:** no ding scene; `customizable_slots` is `null`. Neither path can
  be tested on Ring's side.
- **Workaround:** `ringsim` simulates both, from our own footage.
- **Suggestion:** a ding scene, and a simulated Chime in the Playground.

### 4. Media is refused before the token was granted — Medium

- **Task:** fetch a snapshot "now" (`latest_in_range`) and clips of recent events.
- **Steps:** `POST .../media/image/download` with a range starting a few
  minutes back; clip download for an event before the token existed.
- **Expected:** the media, or the part of the range we may see.
- **Actual:** `403 TIME_RANGE_NOT_AUTHORIZED` for any range reaching back
  before the token was granted, rather than the range being clipped; an
  unrecorded moment answers a 303 redirect that then fails with 416.
- **Workaround:** ask for `at_timestamp` three seconds ago; treat 403 and 416
  as "no recording".
- **Suggestion:** clip the range to the authorised window, and document the
  boundary next to the media endpoints.

### 5. How soon a clip can be downloaded is not documented — Medium

- **Task:** download an event's clip as soon as possible after a webhook.
- **Steps:** on a webhook, called the video download with the event's start time.
- **Expected:** the docs to say when the recording becomes available.
- **Actual:** not stated; asking too early fails. The download takes a start
  and a duration, not an event id, so we must also learn the event's length.
- **Workaround:** poll Event History until the event has an `end`, then
  download start−2 s to end+2 s; retry on 416.
- **Suggestion:** state the delay, or accept an event id on the download.

### 6. A device has no type — Medium

- **Task:** tell the doorbell from cameras and the Chime.
- **Steps:** `GET /v1/devices?include=status,capabilities`.
- **Expected:** a `device_type` (doorbell / camera / chime) attribute.
- **Actual:** none. The only clue is the product image's path
  (`.../DoorbellPro/...`).
- **Workaround:** infer the kind from `image_url`.
- **Suggestion:** a `device_type` attribute.

### 7. Device ids are ~110 characters — Low

- **Task:** name files and folders per device and event.
- **Steps:** used the device id in a clip's file name.
- **Expected:** ids of ordinary length, or a documented maximum.
- **Actual:** ~110 characters; combined with an event time they exceed some
  file-system name limits, and truncation made two events collide.
- **Workaround:** a short hash of the id plus its tail.
- **Suggestion:** document the maximum length.

### 8. Playground tokens last 30 minutes — Medium

- **Task:** run a demo session and record it.
- **Steps:** copied the Playground token into the app.
- **Expected:** a token that lasts a working session, or a refresh flow.
- **Actual:** 30 minutes; the app then gets 401 mid-session.
- **Workaround:** the token is read from a file on every call, so a fresh one
  can be pasted in without a restart; the 401 now says exactly that.
- **Suggestion:** longer sandbox tokens, or a refresh token for the Playground.

### 9. The webhook signature format is hard to find — Low

- **Task:** verify webhook signatures.
- **Steps:** searched the API reference for the header.
- **Expected:** the header name, its format, and an example.
- **Actual:** we learned `X-Signature: sha256=<hex>` (HMAC-SHA256 of the raw
  body) from a community SDK, not from the part of the reference we read.
- **Workaround:** as above.
- **Suggestion:** an example header and a reference verifier in the docs.

### 10. Timestamp units are not stated beside the fields — Low

- **Task:** build snapshot and clip requests.
- **Steps:** read the media endpoints' parameters.
- **Expected:** units next to each `timestamp`.
- **Actual:** not stated there; epoch milliseconds, learned by trying.
- **Suggestion:** "epoch milliseconds" beside every timestamp field.

### 11. The Chime can only play two preset sounds — Medium

- **Task:** speak an alert in the house ("the carer hasn't arrived").
- **Steps:** read the audio playback endpoint.
- **Expected:** text-to-speech, or a short uploaded clip.
- **Actual:** only the two preset slots. An accessibility app has to speak
  through another device.
- **Suggestion:** a text-to-speech or short-upload playback option.

### 12. The API reference is one very long page — Low

- **Task:** find a section quickly (media, webhooks, errors).
- **Steps:** opened the reference.
- **Expected:** a page per resource.
- **Actual:** one page of about 370,000 characters; browsers, search and AI
  tools all struggle with it.
- **Suggestion:** one page per resource, with stable anchors.
