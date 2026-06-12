#!/bin/bash

set -euo pipefail

BASE_DIR="${BASE_DIR:-/home/yuanlin/RS-repair/RS-repair}"
PYTHON_BIN="${PYTHON_BIN:-${BASE_DIR}/.conda/bin/python}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${RESULT_ROOT:-${BASE_DIR}/result/cc_te_lp_smoke/${RUN_ID}}"
SOLVERS="${SOLVERS:-cc_lp,te_lp,et_te_lp}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

IFS=',' read -r -a solver_array <<< "$SOLVERS"

INPUT_DIR="${BASE_DIR}/data/comb/"
RESULT_DIR="${RESULT_ROOT}/comb/"
RELATION="30_0.5_dirty.csv"
FDSET="fdset.txt"
RC="rc.txt"

mkdir -p "$RESULT_DIR"

echo "Start CC-LP / TE-LP / et-TE-LP smoke tests"
echo "Result directory: ${RESULT_DIR}"

relation_name="${RELATION%.csv}"

for current_solver in "${solver_array[@]}"; do
    OUT_FILE="${RESULT_DIR}${RELATION}_${current_solver}.txt"
    LOG_FILE="${RESULT_DIR}${relation_name}_${current_solver}_execution.log"

    if [[ -e "$OUT_FILE" && "${FORCE:-0}" != "1" ]]; then
        echo "[skip] ${OUT_FILE} already exists. Set FORCE=1 to rerun."
        continue
    fi

    echo "======================================================================"
    echo "[smoke] relation: ${RELATION}"
    echo "[solver] ${current_solver}"
    echo "[output] ${OUT_FILE}"
    echo "[log] ${LOG_FILE}"
    echo "======================================================================"

    "$PYTHON_BIN" "${BASE_DIR}/src/driver.py"         --input_dir "$INPUT_DIR"         --result_dir "$RESULT_DIR"         --relation "$RELATION"         --fdset "$FDSET"         --rc "$RC"         --solvers "$current_solver" --strict_sanity 2>&1 | tee "$LOG_FILE"
done

"$PYTHON_BIN" "${BASE_DIR}/summarize_cc_te_quality.py" "$RESULT_ROOT" --output "$RESULT_ROOT/cc_te_lp_quality_summary.csv"
echo "Smoke tests finished."
