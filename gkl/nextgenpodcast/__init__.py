"""nextgenpodcast — the next-generation GKL podcast pipeline.

Successor to `gkl.podcast` (which is preserved untouched and remains
runnable). See docs/nextgenpodcast.md for the spec and decision log.
"""

# One constant per stage so any single stage can be swapped/tuned without
# touching the others. All default to the current recommended Opus.
SEED_MODEL = "claude-opus-4-8"          # Skipper research seed
SHOWRUNNER_MODEL = "claude-opus-4-8"    # rundown planning
SCRIPT_MODEL = "claude-opus-4-8"        # draft / fact-check / punch-up / edit
TAKEAWAYS_MODEL = "claude-opus-4-8"     # takeaways distillation
AD_WRITER_MODEL = "claude-opus-4-8"     # ad copy generation + critic
