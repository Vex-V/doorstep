"""Build the demo day's footage: download the stock clips listed in
`scenarios/demo/SOURCES.md` and write each event's video into
`scenarios/demo/clips/` (1280x720, 25 fps, H.264, so the simulator's page plays
it), trimmed as the scenario expects.

    python scripts/demo_clips.py

The clips are free downloads (Pexels licence) and are not in the repository;
downloads are kept in `scenarios/demo/clips/sources/` and reused.
"""

from __future__ import annotations

import urllib.request
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CLIPS = ROOT / "scenarios" / "demo" / "clips"
W, H, FPS = 1280, 720, 25

# (the file the scenario names, its Pexels video, start s, end s, seconds to
# hold the last frame). The doorbell's are mostly filmed from beside the door,
# where one is mounted; the kitchen's and the living room's from high on a wall.
SCENES = [
    ("0705-parcels-left.mp4", 6994430, 0.0, 1.0, 5.0),
    ("1005-kitchen.mp4", 6970332, 1.0, 12.0, 0.0),
    ("1020-parcels-taken-in.mp4", 6994429, 0.0, 16.5, 0.0),
    ("1112-carer-at-the-door.mp4", 6646620, 3.0, 14.6, 0.0),
    ("1131-carer-leaving.mp4", 6646709, 0.0, 7.0, 0.0),
    ("1402-courier.mp4", 6667245, 1.0, 11.2, 0.0),
    ("1510-on-the-floor.mp4", 3700096, 6.5, 18.8, 0.0),
    ("1640-unexpected-caller.mp4", 11680516, 4.0, 13.0, 0.0),
    ("2350-going-out.mp4", 4066287, 1.0, 12.0, 0.0),
]


def download(video_id: int) -> Path:
    path = CLIPS / "sources" / f"pexels-{video_id}.mp4"
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(f"https://www.pexels.com/download/video/{video_id}/",
                                         headers={"User-Agent": "Mozilla/5.0"})
        print(f"downloading pexels {video_id}")
        with urllib.request.urlopen(request, timeout=120) as resp:
            path.write_bytes(resp.read())
    return path


def fit(img: np.ndarray) -> np.ndarray:
    """Scaled into W x H, letterboxed."""
    h, w = img.shape[:2]
    s = min(W / w, H / h)
    small = cv2.resize(img, (int(w * s) // 2 * 2, int(h * s) // 2 * 2),
                       interpolation=cv2.INTER_AREA)
    canvas = np.zeros((H, W, 3), np.uint8)
    y, x = (H - small.shape[0]) // 2, (W - small.shape[1]) // 2
    canvas[y:y + small.shape[0], x:x + small.shape[1]] = small
    return canvas


def write(name: str, video_id: int, a: float, b: float, hold: float) -> float:
    """[a, b) of the source, resampled to 25 fps, then its last frame held."""
    n, last = 0, None
    with av.open(str(CLIPS / name), "w") as dst:
        vout = dst.add_stream("libx264", rate=FPS)
        vout.width, vout.height, vout.pix_fmt = W, H, "yuv420p"
        vout.options = {"crf": "20", "preset": "medium"}

        def put(img: np.ndarray) -> None:
            nonlocal n
            f = av.VideoFrame.from_ndarray(img, format="rgb24")
            f.pts, f.time_base = n, Fraction(1, FPS)
            n += 1
            for packet in vout.encode(f):
                dst.mux(packet)

        with av.open(str(download(video_id))) as src:
            s = src.streams.video[0]
            s.thread_type = "AUTO"
            nxt = a
            for frame in src.decode(s):
                if frame.time is None or frame.time < nxt:
                    continue
                if frame.time >= b:
                    break
                last = fit(frame.to_ndarray(format="rgb24"))
                while nxt <= frame.time:
                    put(last)
                    nxt += 1 / FPS
        for _ in range(int(hold * FPS)):
            put(last)
        for packet in vout.encode():
            dst.mux(packet)
    return n / FPS


def main() -> None:
    CLIPS.mkdir(parents=True, exist_ok=True)
    for name, video_id, a, b, hold in SCENES:
        print(f"{name:30} {write(name, video_id, a, b, hold):5.2f} s")


if __name__ == "__main__":
    main()
