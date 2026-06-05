"""CLI: write a synthetic HK corpus to a folder for inspection.

    uv run python -m ingest.synth --out /tmp/health_synth --scenario full --seed 0

Writes the HK CSVs (loadable via ``ingest.loaders.batch``) and prints a manifest
summary. Weather/calendar are direct-insert only — they are summarised here but
written to Postgres by ``ingest.flows.make_demo_db``.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ingest.synth.corpus import SCENARIOS, generate_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic Apple-Health corpus.")
    parser.add_argument("--out", required=True, type=Path, help="output folder for HK CSVs")
    parser.add_argument("--scenario", default="full", choices=SCENARIOS)
    parser.add_argument("--seed", default=0, type=int)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    m = generate_corpus(args.out, seed=args.seed, scenario=args.scenario)

    print("─── synthetic corpus ───")
    print(f"scenario:        {m.scenario}")
    print(f"date range:      {m.start_date} … {m.end_date}")
    print(f"csv dir:         {m.csv_dir}")
    print(f"quantity rows:   {m.n_quantity_rows}")
    print(f"workout rows:    {m.n_workout_rows}")
    print(f"weather rows:    {len(m.weather)}")
    print(f"calendar rows:   {len(m.calendar)}")
    print(f"csv files:       {sorted(p.name for p in m.csv_dir.glob('*.csv'))}")


if __name__ == "__main__":
    main()
