import argparse
import csv
import re
from pathlib import Path

RESULT_RE = re.compile(r"^(\d+)_([\d.]+)_dirty\.csv_(cc_lp|te_lp)\.txt$")
FIELDS = {
    "Overall Time cost(in secs.)": "TimeSeconds",
    "Size of subset repair(before PostClean)": "RetainedRows",
    "Size of repair(after PostClean)": "PostCleanRows",
    "FD Consistent(before PostClean)": "FDConsistentBeforePostClean",
    "FD Consistent(after PostClean)": "FDConsistentAfterPostClean",
    "RC Qualified(after PostClean)": "RCQualifiedAfterPostClean",
}


def parse_value(key, value):
    if key in {"RetainedRows", "PostCleanRows"}:
        return int(float(value))
    if key == "TimeSeconds":
        return float(value)
    if key.startswith("FDConsistent") or key.startswith("RCQualified"):
        return value == "True"
    return value


def parse_result(path):
    result = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if ":" not in raw:
            continue
        label, value = raw.split(":", 1)
        if label in FIELDS:
            key = FIELDS[label]
            result[key] = parse_value(key, value.strip())
    return result


def summarize(root, output):
    records = {}
    for path in root.rglob("*.txt"):
        match = RESULT_RE.match(path.name)
        if not match:
            continue
        size, noise, solver = int(match.group(1)), float(match.group(2)), match.group(3)
        dataset = path.parent.relative_to(root).as_posix()
        records.setdefault((dataset, size, noise), {})[solver] = parse_result(path)

    rows = []
    for (dataset, size, noise), pair in sorted(records.items()):
        if "cc_lp" not in pair or "te_lp" not in pair:
            continue
        cc, te = pair["cc_lp"], pair["te_lp"]
        row = {"Dataset": dataset, "Size": size, "Noise": noise}
        for metric in ["RetainedRows", "PostCleanRows", "TimeSeconds"]:
            row[f"CC_LP_{metric}"] = cc.get(metric, "")
            row[f"TE_LP_{metric}"] = te.get(metric, "")
            if metric in cc and metric in te:
                row[f"Delta_{metric}"] = cc[metric] - te[metric]
        for metric in ["FDConsistentBeforePostClean", "FDConsistentAfterPostClean", "RCQualifiedAfterPostClean"]:
            row[f"CC_LP_{metric}"] = cc.get(metric, "")
            row[f"TE_LP_{metric}"] = te.get(metric, "")
        rows.append(row)

    columns = [
        "Dataset", "Size", "Noise",
        "CC_LP_RetainedRows", "TE_LP_RetainedRows", "Delta_RetainedRows",
        "CC_LP_PostCleanRows", "TE_LP_PostCleanRows", "Delta_PostCleanRows",
        "CC_LP_TimeSeconds", "TE_LP_TimeSeconds", "Delta_TimeSeconds",
        "CC_LP_FDConsistentBeforePostClean", "TE_LP_FDConsistentBeforePostClean",
        "CC_LP_FDConsistentAfterPostClean", "TE_LP_FDConsistentAfterPostClean",
        "CC_LP_RCQualifiedAfterPostClean", "TE_LP_RCQualifiedAfterPostClean",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} paired rows to {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize paired CC-LP and TE-LP quality outputs.")
    parser.add_argument("result_root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.result_root / "cc_te_lp_quality_summary.csv"
    summarize(args.result_root, output)
