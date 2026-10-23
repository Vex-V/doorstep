# The demo

Three minutes on one idea: **an older relative living alone, and the family
looking out for them from a distance.** No named characters; "Mum" in the
alerts is just how a family would write them. Every beat is a real feature,
driven by the Ring simulator (`python -m ringsim`) on one day of footage from
three cameras, plus a few seconds of Ring's own Developer Playground at the end.

## The problem, in four lines

1. **A camera says something moved. The family needs to know Mum is all right.**
   Motion alerts fire all day for the postman, a cat and the wind, so they get
   muted, and the one that mattered is missed.
2. **The worries are about absence and timing, not motion.** Nobody in the
   kitchen by half nine. The carer didn't come. Mum went out at midnight.
3. **The worst case is someone on the floor, alone.** A fall where nobody comes
   is what a family fears most, and a camera only says "motion".
4. **Dignity.** Anything that watches a parent must describe, not identify, and
   forget.

> Ring has been adding AI features (event descriptions, video search) for
> subscribers. Say the difference as **alerts the family writes about absence,
> timing and who is expected, checked again until they're sure, and answers
> across the whole day with the clips cited**, never as "Ring can't describe
> video".

## The features, in the order they matter

| # | Feature | Why it matters for an older relative | On screen |
|---|---|---|---|
| 1 | **Still on the floor.** "Tell me if someone is on the floor for more than 2 minutes". A clip shows someone down; Doorstep checks a fresh picture every minute and alerts, and rings the Chime, only if they're still there | A fall with nobody coming is the worst case. Checking again is what keeps it from crying wolf | Alert + Chime |
| 2 | **Carer visits.** The family describes the carer and when they're due. Doorstep notes arrival and departure, and how long they stayed | Peace of mind that care happened, and for how long | "The carer left: at 11:31, after 19 minutes" |
| 3 | **Missed visit alert.** Nobody matching the description by the end of the window: alert, and the Chime in the house | Missed care calls are a real worry | Alert + Chime |
| 4 | **Morning check.** "Tell me if there's no movement in the kitchen by 9:30am" | Not up by the usual time is the oldest sign something's wrong. Needs no vision model at all | Alert |
| 5 | **An unexpected caller.** "Tell me if anyone rings who isn't the carer or a delivery". Doorstep knows what the carer looks like, so the carer and the courier pass and anyone else is flagged | Bogus callers: the family hears about the caller who wasn't expected, not about every ring | Alert + Chime |
| 6 | **Night exit.** "Let me know if Mum goes out the front door between 11pm and 6am" | Wandering, with dementia | Alert |
| 7 | **Alerts in plain English.** The family types a sentence and it's on; the alert's card says exactly what it will do | The family sets it up, no settings menus | The alert's card |
| 8 | **Ask the day.** "Did the carer come, and how long did they stay?" Answers cite clips | Finding out without scrubbing through video | Answer + clip playing |
| 9 | **Notifications and the digest, and privacy:** every ring, visit and alert in one list; the last 24 hours in brief at 8 pm; described, never identified; deleted after a week or at once | The day in one read; dignity | Notifications tab |

Doorstep is not a medical alarm: it doesn't replace a fall pendant. Say so in
the voice-over over the fall; judges will think it.

## The day (`scenarios/demo/scenario.json`)

Three Ring cameras: the front doorbell, a camera in the kitchen and one in the
living room, and a Chime in the hall. Each event is its own video in
`scenarios/demo/clips/`, made by `python scripts/demo_clips.py` from the stock
clips in [SOURCES.md](../scenarios/demo/SOURCES.md).

| Time | Camera | Video | What Doorstep does |
|---|---|---|---|
| 07:05 | Front door | Parcels left on the doormat | Nothing yet |
| 09:30 | | (nobody in the kitchen yet) | **Alert:** no movement in the kitchen, Chime |
| 10:05 | Kitchen | Someone at the kitchen counter, up at last | The clip, on the timeline |
| 10:20 | Front door | Someone takes the parcels in | |
| 11:12 | Front door | The carer, in a VOLUNTEER T-shirt, rings; the door opens | Doorbell notification; **the carer arrived** |
| 11:31 | Front door | The carer at the door, leaving | **The carer left, after 19 minutes** |
| 14:02 | Front door | A courier in red knocks with a parcel | Doorbell notification, no alert |
| 15:10 | Living room | Someone slides off the sofa onto the floor and stays there | Watching… |
| 15:13 | | (still on the floor) | **Alert:** someone on the floor, Chime |
| 16:40 | Front door | A man in a hooded jacket knocks; nobody answers | **Alert:** an unexpected caller, Chime |
| 19:00 | | (nobody) | **Alert:** the evening carer hasn't arrived, Chime |
| 20:00 | | | The digest |
| 23:50 | Front door | Someone comes out and locks the door | **Alert:** going out at night, Chime |

Set up before the day starts, **the visits first**: the unexpected-caller
alert names the carer, and Doorstep writes in what the carer looks like when
it reads the alert.
- **Expected visits** (front door camera):
  - **the carer**, 11:00–12:00: *someone in a white VOLUNTEER T-shirt*. Describe what anyone can see (clothes, a uniform), not gender: the model's guess at gender varies from clip to clip, and the volunteer who leaves is not the one who arrived;
  - **the evening carer**, 18:00–19:00: *a woman in a green care uniform* (never appears).
- **Alerts:**
  - *Tell me if there's no movement in the kitchen by 9:30am*
  - *Tell me if someone is on the floor for more than 2 minutes*
  - *Tell me if anyone rings who isn't the carer or a delivery* (doorbell presses only, so Mum going out at night is not a caller)
  - *Let me know if Mum goes out the front door between 11pm and 6am*

The stock footage is several homes and several people. Keep the voice-over
about "someone" and "Mum" in general, never about who a clip shows.

## The video (under 3:00)

Screen: the Doorstep page large; the simulator page small in a corner. Its
camera view plays each video as it is sent, and its clock, webhooks and Chime
show that Ring is driving everything.

| Time | On screen | Voice-over |
|---|---|---|
| 0:00–0:15 | A phone full of "Motion at Front Door" notifications | "When a parent lives alone, a camera tells you something moved, thirty times a day. What you want to know is whether they're all right." |
| 0:15–0:40 | **Set up:** add the carer (who, what they look like, when). Type "Tell me if anyone rings who isn't the carer or a delivery" → **Add alert** → its card, with the carer's description written in. The other alerts are already there | "The family tells Doorstep who to expect and what matters, in their own words, and it says exactly what it will do." |
| 0:40–0:55 | **Notifications.** 09:30: "No movement in the kitchen this morning". 10:05: the kitchen clip | "Some worries are about what hasn't happened. Nobody in the kitchen by half nine, and the family knows. Then she's up." |
| 0:55–1:20 | 11:12: "The carer arrived". 11:31: "The carer left, after 19 minutes". **View:** ask "Did the carer come, and how long did they stay?" and play the cited clip | "The family sees the carer came and how long they stayed, and can ask about the day, with the clips to prove it." |
| 1:20–1:50 | 15:10: the living-room clip. 15:13: "Someone on the floor", the Chime | "A fall is the worst case. Doorstep doesn't alarm on a single frame: it looks again every minute, and tells the family if they're still down. It's not a medical alarm, but it's a second pair of eyes." |
| 1:50–2:10 | 14:02 courier: a doorbell notification, no alert. 16:40: "An unexpected caller at the door", the Chime | "The courier came, and the family wasn't bothered. This caller wasn't expected, and they're told." |
| 2:10–2:25 | 19:00: "The evening carer hasn't arrived". 23:50: going out at night | "If the carer doesn't come, or Mum goes out at midnight, the family is the first to know." |
| 2:25–2:40 | The last 24 hours in brief; **Clear the timeline** | "The day in one read. People are described, never identified, and footage is deleted after a week." |
| 2:40–2:55 | The Developer Playground: the Package scene; Doorstep picks it up. Architecture card | "This runs on Ring's Partner API, here on Ring's own Developer Playground, and on vidra, our open-source video library." |

**Keep the voice-over over 16:40 neutral** ("a caller who wasn't expected",
never "a scammer"): the licence forbids showing an identifiable person in a
bad light.

**Rehearse it:** `python scripts/rehearse.py` sets Doorstep up as above, plays
the whole day through Doorstep's Next, and checks every alert, visit, ring and
answer the video shows. Measured on this footage: 10/10 checks, the day in
about two and a half minutes.

## Recording runbook

**Before you start:**
1. Run `python scripts/demo_clips.py` (once).
2. Start `python -m ringsim scenarios/demo/scenario.json`, then `python -m doorstep`.
3. Arrange two windows: Doorstep (http://127.0.0.1:8000), large; the simulator
   (http://127.0.0.1:8100), small, in a corner. Record the system audio, for
   the simulator's Chime.
4. On **Set up**, **Delete everything**. Then add, off camera:
   - the evening carer (*a woman in a green care uniform*, front door, 18:00–19:00);
   - the alerts *Tell me if there's no movement in the kitchen by 9:30am*, *Tell me if someone is on the floor for more than 2 minutes* and *Let me know if Mum goes out the front door between 11pm and 6am*.
5. Press **Start over** (twice: it asks to confirm). The day is back at the start, paused.

`python scripts/rehearse.py` is a dry run of the whole day; it deletes
everything when it starts, so redo steps 4 and 5 afterwards.

**Recording.** **Next ▸** goes straight to the next thing that happens and
waits until Doorstep has read it; the status beside it says what it reached.
Each beat is one press or two. (**Auto-play** does the whole day on its own,
3, 6 or 10 s per stop, for a single take.) A pop-up shows each new
notification on any tab; click one to watch its clip.

| Beat | Do | Wait for |
|---|---|---|
| 0:15 setup | **Set up:** add the carer: *the carer*, *someone in a white VOLUNTEER T-shirt*, front door, 11:00–12:00. Type *Tell me if anyone rings who isn't the carer or a delivery* → **Add alert** | The alert's card, naming the VOLUNTEER T-shirt and "presses the doorbell" |
| 0:40 morning | **Notifications.** **Next** (07:05), **Next** (09:30), **Next** (10:05) | "No movement in the kitchen this morning" |
| 0:55 carer | **Next** (10:20), **Next** (11:12), **Next** (11:31) | "The carer arrived", then "The carer left: after 19 minutes" |
| 1:10 ask | **View:** ask *Did the carer come today, and how long did they stay?*; click the first citation | The answer, and the clip playing |
| 1:20 fall | **Next** (14:02, the courier), **Next** (15:10), **Next** (15:13) | "Someone on the floor", and the Chime |
| 1:50 caller | **Next** (16:40) | "An unexpected caller at the door", and the Chime |
| 2:10 evening | **Next** (19:00), **Next** (20:00), **Next** (23:50) | "The evening carer hasn't arrived"; "Someone went out overnight" |
| 2:25 close | **Notifications:** the last 24 hours in brief. **View:** **Clear the timeline** | The digest; an empty timeline |

**Ring's own Developer Playground** (the 2:40 beat, a separate take):
1. Get a fresh token from the Playground in the Ring developer console and
   save it in `.ring_token`.
2. Start a second Doorstep against Ring, with its own data folder. In PowerShell:

   ```powershell
   $env:DOORSTEP_DATA="data-playground"; $env:RING_API_BASE="https://api.amazonvision.com"
   $env:RING_SIM="0"; $env:RING_TOKEN=""; $env:RING_TOKEN_FILE=".ring_token"
   $env:RING_POLL_SECONDS="15"; $env:RING_CHIME_DEVICE=""
   python -m doorstep --port 8001
   ```

3. On http://127.0.0.1:8001 add *Tell me if a parcel is left at the door*.
   Then trigger the Playground's **Package** scene.
4. Within about 30 s the event appears, is described, and the alert fires,
   all through `api.amazonvision.com`.
5. Record the Playground page and Doorstep side by side.

Doorstep only processes Playground events from after it started, so start it
first. The token lasts 30 minutes; paste a new one into `.ring_token` without
restarting.

**Editing:**
- Cut the waits.
- Keep it under 2:55.
- English only.
- No music, or only music you have a licence for (YouTube's Audio Library is fine).
- No third-party logos on screen.
- Upload to YouTube as **Public**, not Unlisted.

The stock footage's licences are in
[SOURCES.md](../scenarios/demo/SOURCES.md).

## Changing the footage

On the simulator's page, **Add camera** (a name, camera or doorbell) and **Add
video**: a file, a time of day, doorbell press or motion, and a note. Both are
saved in `scenario.json`, the video copied into `scenarios/demo/clips/`;
**Remove** takes a video out (the file stays). Or edit `scenario.json` by hand:
each event names its camera and its `clip`. `scripts/demo_clips.py` is how the
demo's own videos are made (a source, a trim, a hold).

**Two things matter in a video:**
- **Its last frame** is what the camera "sees" until its next event: a "still true after N minutes" alert checks that picture. End it on the state you want kept (someone still on the floor).
- **A doorbell clip's picture is its first frame read.** Start a ring's video with the visitor already at the door.
