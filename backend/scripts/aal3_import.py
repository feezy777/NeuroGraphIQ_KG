#!/usr/bin/env python3
"""AAL3 NIfTI + XML → staging CSV (parse-only CLI; DB import removed with legacy workbench).

Usage (from backend/):
  python -m scripts.aal3_import --nii path/to/AAL3v1_1mm.nii --xml path/to/AAL3v1_1mm.xml
  python -m scripts.aal3_import --nii ... --xml ... --out-dir data/runs/my_run
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.io.staging_csv_exporter import export_staging_csvs
from app.parsers.aal3_parser import AAL3Parser


def _make_run_id(nii: Path, xml: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{nii.resolve()}{xml.resolve()}".encode()).hexdigest()[:8]
    return f"{stamp}_{digest}"


def _validate_inputs(nii: Path, xml: Path) -> None:
    if not nii.is_file():
        raise FileNotFoundError(f"NIfTI not found: {nii}")
    if not xml.is_file():
        raise FileNotFoundError(f"XML not found: {xml}")
    nii_stem = nii.stem.lower().replace(".nii", "")
    xml_stem = xml.stem.lower()
    if "aal3" not in nii_stem and "aal3" not in xml_stem:
        print("Warning: filenames do not contain 'aal3'; check you have the correct atlas files.", file=sys.stderr)


def _has_errors(result) -> bool:
    return any(q.get("severity") == "error" for q in result.quality_report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AAL3 parse → staging CSV export")
    parser.add_argument("--nii", required=True, help="Path to AAL3v1_1mm.nii (or .nii.gz)")
    parser.add_argument("--xml", required=True, help="Path to AAL3v1_1mm.xml")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for CSVs (default: data/runs/<run_id>)",
    )
    args = parser.parse_args(argv)

    nii = Path(args.nii).resolve()
    xml = Path(args.xml).resolve()
    _validate_inputs(nii, xml)

    run_id = _make_run_id(nii, xml)
    out_dir = Path(args.out_dir) if args.out_dir else _BACKEND / "data" / "runs" / run_id

    started = datetime.now(timezone.utc)

    print(f"Run ID: {run_id}")
    print(f"Parsing: {nii.name} + {xml.name}")

    aal3 = AAL3Parser(task_id="cli")
    result = aal3.parse_pair(str(nii), str(xml))

    finished = datetime.now(timezone.utc)
    manifest = export_staging_csvs(
        result,
        out_dir,
        run_id=run_id,
        nii_path=str(nii),
        xml_path=str(xml),
        started_at=started,
        finished_at=finished,
    )

    print(f"CSV output: {out_dir.resolve()}")
    print(
        f"Regions: {manifest['counts']['regions']} | Terms: {manifest['counts']['terms']} | "
        f"Mappings: {manifest['counts']['mappings']}"
    )
    print(f"Hemisphere: {manifest['by_hemisphere']} | Spatial filled: {manifest['spatial_filled']}")
    print(f"Quality: {manifest['quality']}")

    if _has_errors(result):
        print("Completed with parser errors (see quality_report.csv).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
