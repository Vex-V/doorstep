# Devpost submission: Doorstep

Every field of the submission form, ready to paste. Fill in the two URLs marked
**TODO** once the video is uploaded and the repository is pushed.

---

## Project name

Doorstep

## Elevator pitch (tagline)

Ring for an older relative who lives alone: alerts the family writes in plain
English, carer visits tracked, and a fall noticed when nobody comes.

## Tracks and mini challenges

- **Primary track:** Ring
- **Mini challenge:** Open Source

## Links

- **Demo video:** TODO (YouTube, public, under 3 minutes)
- **Code repository:** TODO `https://github.com/Vex-V/doorstep` (public, Apache-2.0)

## Built with

python, fastapi, ring-partner-api, ring-developer-playground, openai, vidra,
pyav, opencv, sentence-transformers, sqlite, server-sent-events

---

## About the project

### Inspiration

When a parent lives alone, their Ring cameras tell the family that something
moved, thirty times a day. The alerts get muted, and the one that mattered is
missed. The questions a family actually has are different: *Is Mum up? Did the
carer come, and how long did they stay? Who rang the bell?* And the one they
dread: *has she fallen, with nobody there?*

### What it does

Doorstep runs on a household's Ring cameras (the doorbell, and cameras inside
if the family has them) and tells the family what they need to know, on one
page with three tabs: **Set up**, **Notifications** and **View**.

- **Alerts written in plain English.** "Tell me if there's no movement in the
  kitchen by 9:30am." "Tell me if someone is on the floor for more than 2
  minutes." "Tell me if anyone rings who isn't the carer or a delivery." "Let
  me know if Mum goes out between 11pm and 6am."
  - Doorstep turns each sentence into a rule, and the alert's card says back
    exactly what it will do, generated from the rule itself.
  - Three kinds: *it happened*, *it's still true after N minutes*, and *it
    didn't happen by a deadline*. The last two are what motion alerts can't
    express.
  - *Still true* checks a fresh picture every minute and alerts only if it
    still holds: someone on the floor at 15:10 and still there at 15:13 is an
    alert; someone who got up is not.
  - An alert can be about doorbell presses only: "anyone rings" never fires
    on Mum going out.
  - Every alert sounds the Ring Chime in the house.
- **Expected visits.** The family describes the carer by what they look like
  and wear, and gives the time window.
  - Doorstep records when someone matching arrives and leaves, and how long
    they stayed.
  - If nobody matching has come by the end of the window, it alerts the family.
  - An alert can name them: in "Tell me if anyone rings who isn't the carer or
    a delivery", Doorstep writes in what the carer looks like, so the carer
    and the courier pass and only an unexpected caller reaches the family.
- **Ask the day.** "Did the carer come, and how long did they stay?" → "Yes.
  The carer arrived at 11:12 and left at 11:31, staying 19 minutes." Every
  answer cites the clips, which play at the right second.
- **A digest** of the last 24 hours at 8 pm, every line linked to its clip.

- **Notifications:** every doorbell press, visit and alert in one list, each
  opening its clip, with the last 24 hours in brief at 8 pm.
- **View:** every clip on one timeline, as it arrives, to watch or ask about;
  cleared with one button.

**Privacy:** people are described by appearance, never identified or
face-matched. Footage is deleted after a week, or at once from the page.
Doorstep is not a medical alarm and doesn't replace a fall pendant.

### How we built it

- **Ring Partner API.**
  - Doorstep's Ring client calls devices, Event History, clip and snapshot
    download (following the 303 to the pre-signed URL without the token) and
    Chime playback.
  - It receives Ring's webhooks: HMAC-SHA256 verified, deduplicated on
    `request_id`, answered within 5 s.
  - The same client runs against Ring's **Developer Playground**. The
    Playground sends no webhooks, so Doorstep polls Event History and feeds
    each new event in as a webhook would arrive.
- **Ring simulator (`ringsim`, in the repo).** The Playground has two scenes,
  no doorbell press, no webhooks and no Chime. So we built a simulator that
  serves a day of videos, each at a time of day, as the Partner API over HTTP:
  - devices, history, media through 303s, a Chime;
  - webhooks signed like Ring's, retried six times;
  - a page to add or remove videos and play the day on schedule, one after
    another, or by hand, with a camera view and the API calls it receives.

  On the dashboard, **Next** goes straight to the next thing that happens (a
  video, or one of Doorstep's own deadlines) and waits until it has been read,
  so a whole day plays in under two minutes with no dead time.

  Doorstep talks to it with the same client; only the base URL changes.
- **Every event's clip goes through vidra**, our open-source video RAG
  library. It samples frames and asks several questions in one pass: a general
  description, each alert's own question, each expected visit's "does someone
  matching this description appear?". It stores the answers and indexes them
  for search. A "still true" alert then asks its question of a fresh snapshot
  every few minutes, through the Partner API.
- **Decisions are code, not the model.**
  - The model answers fixed-format questions ("yes / no / cannot tell"), and
    plain code applies the rules to those answers. "Cannot tell" never fires
    an alert and never clears one.
  - The sentence on each alert is generated from the rule itself, so what
    the family reads is exactly what runs.
- **Ask** plans a search with an LLM, runs vidra's hybrid search over the
  period's clips, and answers only from that evidence and the visit records.
- **Stack.** FastAPI and SQLite, server-sent events to the page, and
  OpenAI's vision model through vidra.

### Challenges we ran into

- **The Playground.**
  - Its two scenes report as `on_demand`, and it ignores the `event_types`
    filter.
  - Media is refused (403) for any time before the token was granted.
  - It sends no webhooks, has no doorbell press and no Chime.

  We built the simulator so the full product could be shown working through
  Ring's API shapes, and kept the Playground path working too. The friction
  log has the details.
- **"Didn't happen" is hard to ask a camera.** It takes a deadline, the day's
  clips, and waiting for clips still being read before deciding.
- **One frame is not a fall.** Bending down looks like falling; the answer was
  to keep checking and alert only on "still down".
- **Stock footage of falls barely exists,** so the demo's fall is someone
  sliding off a sofa onto the floor.
- **Matching a carer by description is noisy.**
  - The model's guess at gender changed between runs, so descriptions should
    use hair and clothes.
  - A carer leaving is often described as "at the door", so a later sighting
    counts as the departure.

### Accomplishments that we're proud of

- **The whole demo day checks itself.** A rehearsal script sets Doorstep up,
  plays the day through three cameras, and checks every alert (each fired
  once, at the right time, on the right camera), the carer's visit, the rings,
  the Chime, an answer and the digest. 10/10 with the real models, the day in
  about two and a half minutes.
- **Rules a family can read,** including the "it didn't happen"
  kind, run by deterministic code over the model's answers.

### What we learned

Families don't want more motion alerts. They want to ask about absence and
timing, and to be told only when something is still wrong. Video understanding
is good enough for that today when the model only answers narrow questions and
the decisions stay in code.

### What's next

- Push notifications to the family's phone.
- Ring account linking for real households.
- Several cameras per home.
- A local vision model, so footage never leaves the house.
- Taking these features to the Ring Appstore.

---

## Project existed before the hackathon?

**Doorstep** was started during the submission window: first code on
18 October 2026. Everything in the repository is new, apart from the vendored
copy of vidra (below). `BUILT.md` in the repository logs what was built each
day.

**vidra**, the video library Doorstep is built on, is our own and is entered in
the Open Source mini challenge.
- Its repository's first commit (25 August 2026, six days before the window
  opened) was a 3,700-line ingestion prototype.
- The `vidra` package itself was written inside the window: 146 files and
  about 17,000 lines across 114 commits, from 31 August onwards.

---

## Open Source mini challenge

- **Contribution URL:** https://github.com/Vex-V/VIDRA
- **Project repository URL:** TODO `https://github.com/Vex-V/doorstep`
- **GitHub username:** Vex-V

**What we did.** We built **vidra**, an open-source Python library for
retrieval over video. A video goes in; searchable moments come out.
- The picture and the soundtrack are read onto one shared timeline of chunks.
- Samplers decide which frames are worth a vision model's time: on change, on
  people, on text, or on a stride.
- The model answers your own questions with strict structured schemas.
- The answers are embedded for hybrid search (meaning and keywords, fused by
  rank).
- Higher-level aggregates (summaries, chapters, linked people) are built over
  the whole video, and a live-stream pipeline answers frames as they arrive.

**How it works.**
- **Two tiers.** `video_rag` turns a video into answers and an index;
  `aggregates` answers questions over those answers without touching the video
  again.
- **Components hand off through files,** so each step is resumable and only
  re-pays a model when its inputs actually changed.
- **Any model provider:** OpenAI, Anthropic, any OpenAI-compatible server, or
  local models.
- **Tested end to end:** a `library_check` suite runs every stage and public
  function and fails on any regression.

**Why it matters.** Every "ask your camera" product needs the same hard
middle: which frames to look at, what to ask, how to keep answers searchable,
and how not to pay twice.
- **Doorstep was built on vidra in five days.** Each alert is compiled into a
  vidra question, `describe.ask` answers questions about one doorbell
  snapshot, `video_rag` reads each clip, and `search` powers "ask the day".
- **For Ring developers,** that is the layer between a webhook and a useful
  answer.

---

## Product feedback

### Ring Partner API

- **What we used it for:**
  - `GET /v1/devices` to find the doorbell and cameras;
  - Event History, to find events and their end times, and as the event source
    on the Playground;
  - video and image download, for each event's clip and the doorbell snapshot;
  - device configurations and audio playback, to sound the Chime when an alert
    fires;
  - webhooks (HMAC-verified), as the event source.
- **What worked well:**
  - The JSON:API shapes are consistent, and errors carry codes.
  - Media through a pre-signed redirect is fast and keeps the token out of the
    media fetch.
  - Clip downloads by time range made the "pad two seconds either side" clip
    easy.
  - Snapshots at a timestamp gave us the exact moment of a doorbell press.
- **What needs work:**
  - There's no device type: we inferred doorbells from the product image's
    path.
  - Event History ignores `event_types`.
  - The delay before a clip can be downloaded isn't documented, and the
    download takes a start and duration rather than an event id.
  - The authorised-time-range rule (403) isn't documented beside the media
    endpoints, and timestamp units aren't stated beside the fields.
  - The Chime plays only two preset sounds, with no text-to-speech.
  - The reference is a single very long page.
- **Onboarding:**
  - The developer console needed identity verification first.
  - Then client credentials and the HMAC signing key, then a Playground token.
  - The first real API call (devices) worked within minutes of having a token.
  - Most of the time went into learning what the Playground does and doesn't
    emit.
- **Would we build with it again?** Yes. Clips, snapshots, history and webhooks
  are exactly the right primitives for a video-understanding product. With
  device types, documented media timing and a richer sandbox, it would be much
  quicker to build on.

### Ring Developer Playground (simulator)

- **What we used it for:**
  - running Doorstep against Ring's real API with a simulated doorbell;
  - devices, history, snapshot and clip download, verified on 20 October;
  - both scenes read by the vision model and searchable.
- **What worked well:** no device needed; real API responses; real media.
- **What needs work:**
  - Scenes arrive as `on_demand`, not `motion`.
  - No webhooks, no doorbell-press scene and no Chime, so the doorbell and
    webhook paths can't be tested on Ring's side.
  - Tokens last 30 minutes.
  - Media is refused for times before the token.
- **Onboarding:** quick once we found it. The token is the only credential
  needed, and the console page explains the scenes.
- **Would we use it again?** Yes, as the reference for real API behaviour. We
  built `ringsim` (in our repository, Apache-2.0) to cover what it doesn't, and
  would gladly see an official equivalent.

### OpenAI API (through vidra)

- **What we used it for:** the vision model that describes snapshots and clips
  (`gpt-6-luna`), and the LLM that compiles alerts, plans searches, answers
  questions and writes the digest.
- **Worked well:** strict JSON schemas, so every answer is machine-checkable.
- **Needs work:** a reasoning model spends part of its output budget on
  reasoning, so limits had to be raised.
- **Again?** Yes, behind vidra's model interface, so it can be swapped for a
  local model.

### AWS

No AWS services were used; we are not entering the AWS Builder mini challenge.

---

## Feature requests

| Request | Why it matters for Doorstep | Priority |
|---|---|---|
| Playground scenes that emit real event types and fire the app's webhooks, plus a doorbell-press scene | The webhook and doorbell paths are the heart of any Ring app, and can't be tested against Ring today | **Critical** |
| A `device_type` on devices | Telling a doorbell from a camera without parsing image URLs | Important |
| Clip download by event id, or a documented availability delay | Fetching an event's clip reliably as soon as it exists | Important |
| Chime playback of text-to-speech or a short uploaded clip | Speaking an alert in the house ("the carer hasn't arrived") for someone with low vision | Important |
| Longer-lived or refreshable Playground tokens | 30 minutes ends a demo session mid-recording | Important |
| A Playground scene from your own footage (what `ringsim` does) | Testing an app's own scenarios end to end on Ring's side | Nice-to-have |
| One reference page per resource | Finding the media and webhook sections quickly | Nice-to-have |

---

## Friction log

Paste the twelve entries from [FRICTION.md](../FRICTION.md). Each has the task,
the steps, expected vs. actual, a severity, the workaround and a suggestion.

---

## Testing instructions (for judges)

No Ring device or account is needed. You need Python 3.11+ and an OpenAI API
key.

```bash
pip install -e .[dev]
cp .env.example .env            # set OPENAI_API_KEY
python scripts/demo_clips.py    # downloads the demo day's videos (free stock clips)
python -m ringsim scenarios/demo/scenario.json     # terminal 1
python -m doorstep                                 # terminal 2
```

- **Pages:** Doorstep at http://127.0.0.1:8000, and the Ring simulator at
  http://127.0.0.1:8100.
- **Run the whole demo, checked beat by beat:** `python scripts/rehearse.py`.
- **Tests, no key needed:** `pytest`.
