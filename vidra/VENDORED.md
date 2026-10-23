# vidra, vendored

This folder is a copy of **vidra**, the video RAG library Doorstep is built on
(clips in; answers to questions about them, and a searchable index, out). It
is maintained in its own repository; this copy is here so Doorstep installs
and runs from this repository alone.

- Copied from vidra at commit `c1ad4f1` (2026-10-15), unchanged.
- Doorstep uses: `video_rag` (a clip through sampling, describing and
  embedding), `describe.add_question` / `ask_async` (its own questions, and
  single snapshots), `search` over a `Folder` database, and `Models` with
  `OpenAI`, `LocalEmbedder` and `Stub`.
- Its dependencies are listed in Doorstep's `pyproject.toml`. Only the core
  install and the local embedder are needed: no audio models, no detectors.

To update it, copy the `vidra/` package from the vidra repository over this
folder and keep this file.
