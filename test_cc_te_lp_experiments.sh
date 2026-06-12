#!/bin/bash

set -euo pipefail

BASE_DIR="${BASE_DIR:-/home/yuanlin/RS-repair/RS-repair}"
PYTHON_BIN="${PYTHON_BIN:-${BASE_DIR}/.conda/bin/python}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${RESULT_ROOT:-${BASE_DIR}/result/cc_te_lp_experiments/${RUN_ID}}"
# SOLVERS="${SOLVERS:-cc_lp,te_lp,et_te_lp}"
SOLVERS="${SOLVERS:-cc_lp,te_lp}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="python3"
fi

IFS=',' read -r -a solver_array <<< "$SOLVERS"

TASKS=(
    "data/input_data_acs/non_chain_FD/|non_chain_fdset.txt|NATIVITY_rc.txt|acs_nonchain/"
    "data/input_data_acs/chain_FD/|chain_fdset.txt|REGION_rc.txt|acs_chain/"
    "data/input_data_compas/chain_FD/|chain_fdset.txt|SEX_rc.txt|compas_chain/"
    "data/input_data_compas/non_chain_FD/|non_chain_fdset.txt|SEX_rc.txt|compas_nonchain/"
)

echo "Start CC-LP / TE-LP / et-TE-LP experiments"
echo "Result root: ${RESULT_ROOT}"

for task in "${TASKS[@]}"; do
    IFS='|' read -r input_subdir fdset rc result_name <<< "$task"

    INPUT_DIR="${BASE_DIR}/${input_subdir%/}/"
    RESULT_DIR="${RESULT_ROOT}/${result_name%/}/"

    mkdir -p "$RESULT_DIR"

    for csv_path in "${INPUT_DIR}"*.csv; do
        [[ -e "$csv_path" ]] || continue

        relation="$(basename "$csv_path")"
        relation_name="${relation%.csv}"

        for current_solver in "${solver_array[@]}"; do
            OUT_FILE="${RESULT_DIR}${relation}_${current_solver}.txt"
            LOG_FILE="${RESULT_DIR}${relation_name}_${current_solver}_execution.log"

            if [[ -e "$OUT_FILE" && "${FORCE:-0}" != "1" ]]; then
                echo "[skip] ${OUT_FILE} already exists. Set FORCE=1 to rerun."
                continue
            fi

            echo "======================================================================"
            echo "[dataset] ${result_name%/}"
            echo "[relation] ${relation}"
            echo "[fd/rc] ${fdset} / ${rc}"
            echo "[solver] ${current_solver}"
            echo "[output] ${OUT_FILE}"
            echo "[log] ${LOG_FILE}"
            echo "======================================================================"

            "$PYTHON_BIN" "${BASE_DIR}/src/driver.py"                 --input_dir "$INPUT_DIR"                 --result_dir "$RESULT_DIR"                 --relation "$relation"                 --fdset "$fdset"                 --rc "$rc"                 --solvers "$current_solver" --strict_sanity 2>&1 | tee "$LOG_FILE"
        done
    done
done

"$PYTHON_BIN" "${BASE_DIR}/summarize_cc_te_quality.py" "$RESULT_ROOT" --output "$RESULT_ROOT/cc_te_lp_quality_summary.csv"
echo "Experiments finished."
