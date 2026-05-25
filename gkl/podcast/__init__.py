"""gkl.podcast — podcast generation pipeline.

The pipeline runs in phases:
    1. datapack  — assemble raw datasets for a given segment + week
    2. skipper_seed — produce suggested topics via Skipper (Opus 4.6)
    3. source_builder — partition into three-act Studio Podcast source docs
    4. voice — render voice tracks via ElevenLabs Studio Podcast API
    5. music/sfx/ads — generate reusable assets (one-time) + per-episode ad selection
    6. mixer — stitch slots into the final mp3 via ffmpeg
    7. pipeline — orchestrate end-to-end

See docs/gkl-podcast.md for the full plan and segment design.
"""

SKIPPER_PODCAST_MODEL = "claude-opus-4-6"
