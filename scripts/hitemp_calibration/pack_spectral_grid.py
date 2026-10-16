"""Pack the offline HITEMP alpha grid as little-endian float32 + zlib.

The original CSV remains the audit/source artifact. The compact payload stores
only alpha_nu in manifest-defined (T, P, composition, wavenumber) order.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import struct
import zlib
from pathlib import Path

MAGIC = b"HITGRD01"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("data"))
    ap.add_argument("--input", default="spectral_grid_alpha_tau.csv")
    ap.add_argument("--output", default="spectral_grid_alpha_f32.z")
    args = ap.parse_args()
    root = args.data_dir
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    meta = manifest["spectral_grid"]
    axes = meta["spectral_grid_cm-1"]
    nnu = int(axes["points"])
    ncond = len(meta["temperature_K"]) * len(meta["pressure_atm"]) * len(meta["compositions"])
    count = nnu * ncond
    values = array.array("f")
    input_path = root / args.input
    if sha256(input_path) != meta["output_sha256"]:
        raise SystemExit("input CSV SHA-256 does not match manifest")
    with input_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        expected_fields = {"alpha_m-1", "temperature_K", "pressure_atm", "composition", "wavenumber_cm-1"}
        if not expected_fields.issubset(reader.fieldnames or []):
            raise SystemExit("CSV is missing required fields")
        for row in reader:
            value = float(row["alpha_m-1"])
            if not (value >= 0.0 and value < float("inf")):
                raise SystemExit("invalid alpha value")
            values.append(value)
    if len(values) != count:
        raise SystemExit(f"row count mismatch: expected {count}, got {len(values)}")
    if values.itemsize != 4:
        raise SystemExit("platform float array is not float32")
    if __import__("sys").byteorder != "little":
        values.byteswap()
    raw = values.tobytes()
    header = {
        "dtype": "<f4", "shape": [len(meta["temperature_K"]), len(meta["pressure_atm"]),
                                   len(meta["compositions"]), nnu],
        "order": "C", "compression": "zlib", "uncompressed_bytes": len(raw),
        "source_csv_sha256": meta["output_sha256"],
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    output = root / args.output
    output.write_bytes(MAGIC + struct.pack("<I", len(header_bytes)) + header_bytes + zlib.compress(raw, 9))
    packed_meta = {"file": args.output, "format": "HITGRD01", "dtype": "<f4",
                   "compression": "zlib", "shape": header["shape"],
                   "uncompressed_bytes": len(raw), "bytes": output.stat().st_size,
                   "sha256": sha256(output), "source_csv_sha256": meta["output_sha256"]}
    meta["compact_binary"] = packed_meta
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(packed_meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
