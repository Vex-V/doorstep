# The demo day

`scenario.json` scripts one day at an older relative's home, seen by its
front doorbell, a kitchen camera and a living-room camera (the beats are in
[docs/demo.md](../../docs/demo.md)). Each event is a video of its own at a time
of day, in `clips/`:

    python scripts/demo_clips.py

downloads the stock clips listed in [SOURCES.md](SOURCES.md) and trims each
into the file its event names. The Ring simulator serves each as that time's
recording, and sends its event to the app as a signed Ring webhook; its page
plays each video in a camera view as it is sent.

| At | Camera | What happens | What Doorstep should do |
|---|---|---|---|
| 07:05 | Front door | Parcels left on the doormat | Nothing yet |
| 10:05 | Kitchen | Someone at the kitchen counter | After the 09:30 "no movement in the kitchen" alert |
| 10:20 | Front door | Someone at the door takes the parcels in | Nothing |
| 11:12 | Front door | The carer, in a VOLUNTEER T-shirt, rings; the door opens | A doorbell notification; the carer's visit: arrived |
| 11:31 | Front door | The carer at the door, leaving | The visit: left, 19 minutes |
| 14:02 | Front door | A courier knocks with a parcel | A doorbell notification, no alert |
| 15:10 | Living room | Someone slides off the sofa onto the floor and stays there | "Still on the floor" alert, a few minutes later |
| 16:40 | Front door | A man in a hooded jacket knocks; nobody answers and he leaves | The unexpected-caller alert |
| 23:50 | Front door | Someone comes out and locks the door | The night-exit alert |

The evening carer (18:00–19:00) never comes: that is the missed-visit alert.

Videos added on the simulator's page are copied into `clips/` and saved in
`scenario.json`. The videos and the downloads are not committed (`.gitignore`).
