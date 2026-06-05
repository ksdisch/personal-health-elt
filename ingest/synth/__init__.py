"""Deterministic synthetic Apple-Health corpus generator.

Fabricates a SimpleHealthExport-schema CSV corpus (+ direct-insert weather /
calendar frames) that the EXISTING loaders ingest unchanged, so a fresh agent
can stand up the entire warehouse in an isolated ``health_demo`` database with
**no iOS export and no credentials**. See ``docs/design/autonomous-build-plan.md``.

Determinism: everything is driven by a fixed ``seed`` and anchored to fixed
2024 calendar dates, so golden-snapshot digests of the resulting marts are
stable run-to-run. The ``full`` scenario stitches every ``recovery_signal``
branch (insufficient_data / strained / well_recovered / neutral) across one
timeline so a single build exercises the flagship mart end to end.
"""

from __future__ import annotations

from ingest.synth.corpus import (
    SCENARIOS,
    CorpusManifest,
    generate_corpus,
)

__all__ = ["SCENARIOS", "CorpusManifest", "generate_corpus"]
