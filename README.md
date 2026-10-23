# Doorstep

**Ring cameras for an older relative living alone, and the family looking out
for them.** A camera says something moved; a family needs to know Mum is all
right.

- **Alerts in plain English.** "Tell me if there's no movement in the kitchen
  by 9:30am." "Tell me if someone is on the floor for more than 2 minutes."
  "Tell me if anyone rings who isn't the carer or a delivery." "Let me know if
  Mum goes out between 11pm and 6am." An alert is on as soon as it's added,
  and its card says exactly what it will do. Alerts sound the Chime in the
  house.
- **Checked again before it alarms.** "Still on the floor after 2 minutes"
  looks at a fresh picture every minute and alerts only if it's still true.
- **Carer visits.** Describe the carer ("someone in a white VOLUNTEER
  T-shirt") and when they're due. Doorstep notes when they arrive and leave,
  and alerts if nobody matching has come by the end of the window. An alert
  can name them, and Doorstep writes in what they look like.
- **One page:** **Set up** (alerts, visits), **Notifications** (every ring,
  visit and alert, and the last 24 hours in brief) and **View** (every clip
  received, on one timeline you can clear, and questions: "Did the carer
  come, and how long did they stay?", answered with the clips cited).

Doorstep is not a medical alarm and doesn't replace a fall pendant.

People are described by what they look like, never identified. Footage is
deleted after a week, or at once, from the page.

## How it works

```
 Ring ──signed webhook──► /ring/webhook ──► worker
   │                                          └─ every event ─► clip ─► vidra ─► answers + index
   │                                                                     ├─► rules engine ─┐
   │                                                                     └─► visits ───────┴─► alerts, Chime
   └── Partner API: devices · Event History · clip & snapshot download · Chime
 every simulated minute: snapshots for "still true" rules, "nobody by 9:30"
 and missed-visit deadlines, the 8 pm digest, retention
```

- **Ring Partner API** ([doorstep/ring/client.py](doorstep/ring/client.py)): devices,
  Event History, clip download, snapshots, Chime playback; webhooks verified
  with HMAC-SHA256 and deduplicated on `request_id`
  ([doorstep/ring/webhooks.py](doorstep/ring/webhooks.py)).
- **vidra** reads each clip: frames sampled, every question answered by a vision
  model, the answers embedded into a searchable index. Doorstep asks the
  `doorstep` question of every clip, plus each rule's and each expected visit's
  own question for that camera ([doorstep/footage/clips.py](doorstep/footage/clips.py)).
- **Rules** ([doorstep/alerts/](doorstep/alerts/)) come in three kinds:
  `on_event` (a clip shows something, inside a time window), `persists` (still
  true after N minutes, checked by snapshots), `absent` (nothing happened by a
  deadline; with no question, any motion counts and no model is called). An
  unsure answer ("cannot tell") never fires and never clears a rule.
- **Expected visits** ([doorstep/alerts/visits.py](doorstep/alerts/visits.py))
  match the family's description against each clip (appearance and clothing,
  never a face), record arrival and departure, and alert once if the window
  closes with nobody matching.
- **Ask** ([doorstep/answers/ask.py](doorstep/answers/ask.py)) plans the search
  with an LLM, searches the clips of the period with vidra's hybrid search, and
  answers from that evidence and the visit records only, citing clips.

## Repository

```
doorstep/              the app
  app.py               the server: start-up, and the routers below
  worker.py            the queue, the clip path, and the per-minute ticks
  core/                settings, the clock, SQLite, the live-update bus, the models
  ring/                Ring: the Partner API client, webhooks, Event History polling
  footage/             what the vision model is asked: questions, and the clip path
  alerts/              rules (and their compiler and engine), expected visits, notify
  answers/             ask, and the digest of the last 24 hours
  routes/              the HTTP API: ring, family, alerts, door
  static/              the family's page: Set up, Notifications, View
ringsim/               the Ring Partner API simulator (imports nothing from doorstep)
vidra/                 the video RAG library Doorstep is built on, vendored (see VENDORED.md)
scenarios/demo/        the demo day: which video happens when
scripts/rehearse.py    runs the demo's beats against the simulator, timed
scripts/demo_clips.py  downloads the demo day's videos (free stock clips)
docs/demo.md           the demo: the problem, the features, the video
tests/                 pytest: webhooks, rules, visits, the simulator, end to end
BUILT.md · FRICTION.md what was built in the hackathon window, and the friction log
```

## Run it

Python 3.11+, about 1.5 GB of disk (CPU PyTorch, for the local search embedder),
and an OpenAI API key for the vision model. No Ring device and no Ring account
needed.

```bash
pip install -e .[dev]                # Doorstep, the Ring simulator, and vidra (vendored)
cp .env.example .env                 # then set OPENAI_API_KEY in it
python scripts/demo_clips.py         # once: the demo day's videos, from free stock clips

python -m ringsim scenarios/demo/scenario.json      # terminal 1: Ring, simulated
python -m doorstep                                  # terminal 2: Doorstep
```

Then open:

- http://127.0.0.1:8000: Doorstep;
- http://127.0.0.1:8100: the Ring simulator.

Add an expected visit and an alert on **Set up**, then press **Next** to go
straight to the next thing that happens (a video, or one of Doorstep's own
deadlines), or **Auto-play** to go through the whole day; **Start over** plays
it again. `python scripts/rehearse.py` runs the whole demo, beat by beat, and
checks each one.

**The Ring simulator.** `ringsim` is a day of videos, each at a time of day,
served as Ring's Partner API over HTTP:
- devices and Event History;
- clip and snapshot download through 303 redirects;
- a Chime;
- signed webhooks pushed to the app for each video.

On its page you add a camera (a name; camera or doorbell), add a video (a
file, a time, doorbell press or motion) or remove one, and play the day **on schedule** (the clock runs, at up to 300×),
**one after another** (each video in turn, a set gap apart), or **by hand**
(nothing is sent until you press Send).

Send works in any mode. A video still ahead of the clock happens at its own
time (the clock jumps there); one already past happens again now, as a
doorbell pressed again would. Either way it reaches the app as a new event,
and so does the whole day played again: each run's events get their own ids,
as Ring's do.

Doorstep talks to it with the same client it uses for `api.amazonvision.com`;
only the base URL differs. It imports nothing from Doorstep, so any Ring app
can use it.

**With Ring's Developer Playground** (Ring's own simulated doorbell): in `.env`,
set `RING_API_BASE=https://api.amazonvision.com`, `RING_SIM=0`, `RING_TOKEN=`,
`RING_TOKEN_FILE=.ring_token` (paste the 30-minute token in; it is re-read on
every call), `RING_POLL_SECONDS=15` and `RING_CHIME_DEVICE=`. The Playground
sends no webhooks, so Doorstep polls Event History and feeds each new event in
exactly as a webhook would arrive.

**With a real Ring account:** as for the Playground, with `RING_TOKEN` and
`RING_WEBHOOK_SECRET` from the developer portal, and the app's webhook URL
pointed at `https://<your host>/ring/webhook`.

```bash
pytest     # webhooks, rules, visits, the simulator through the Ring client,
           # and the whole flow end to end with a fake model: no key needed
```

## Privacy

- No face recognition and no names: people are described by appearance only.
- Footage stays on the machine running Doorstep; frames go to the configured
  vision model's provider (OpenAI by default). A local model (Ollama, through
  vidra's `Chat`) keeps everything on the machine.
- Delete a clip, a day, or everything, from the page; retention deletes
  anything older than `DOORSTEP_RETENTION_DAYS` (7).

## Licence

Apache 2.0.
