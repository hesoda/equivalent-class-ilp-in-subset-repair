#!/bin/bash
set -euo pipefail

BASE_DIR="${BASE_DIR:-/home/yuanlin/RS-repair/RS-repair}"
PYTHON_BIN="${PYTHON_BIN:-${BASE_DIR}/.conda/bin/python}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${RESULT_ROOT:-${BASE_DIR}/result/exact_reproduction/${RUN_ID}}"
REAL_SOLVERS="${REAL_SOLVERS:-ilp_baseline,equiv_class_ilp}"
SYNTHETIC_EC_SOLVERS="${SYNTHETIC_EC_SOLVERS:-equiv_class_ilp}"
SYNTHETIC_PAIRWISE_SOLVERS="${SYNTHETIC_PAIRWISE_SOLVERS:-ilp_baseline}"

if [[ ! -x "$PYTHON_BIN" ]]; then PYTHON_BIN=python3; fi

run_task() {
    local input_subdir="$1" fdset="$2" rc="$3" result_name="$4" solvers="$5" size_policy="${6:-all}"
    local input_dir="${BASE_DIR}/${input_subdir%/}/" result_dir="${RESULT_ROOT}/${result_name%/}/"
    mkdir -p "$result_dir"
    IFS=',' read -r -a solver_array <<< "$solvers"
    for csv_path in "${input_dir}"*.csv; do
        [[ -e "$csv_path" ]] || continue
        local relation relation_name size
        relation="$(basename "$csv_path")"; relation_name="${relation%.csv}"; size="${relation%%_*}"
        if [[ "$size_policy" == "lt100k" && "$size" -ge 100000 ]]; then continue; fi
        for solver in "${solver_array[@]}"; do
            local out_file="${result_dir}${relation}_${solver}.txt" log_file="${result_dir}${relation_name}_${solver}_execution.log"
            if [[ -e "$out_file" && "${FORCE:-0}" != "1" ]]; then continue; fi
            "$PYTHON_BIN" "${BASE_DIR}/src/driver.py" --input_dir "$input_dir" --result_dir "$result_dir" --relation "$relation" --fdset "$fdset" --rc "$rc" --solvers "$solver" --strict_sanity 2>&1 | tee "$log_file"
        done
    done
}

run_task data/input_data_acs/chain_FD chain_fdset.txt REGION_rc.txt acs_chain "$REAL_SOLVERS"
run_task data/input_data_acs/non_chain_FD non_chain_fdset.txt NATIVITY_rc.txt acs_nonchain "$REAL_SOLVERS"
run_task data/input_data_compas/chain_FD chain_fdset.txt SEX_rc.txt compas_chain "$REAL_SOLVERS"
run_task data/input_data_compas/non_chain_FD non_chain_fdset.txt SEX_rc.txt compas_nonchain "$REAL_SOLVERS"
run_task data/synthetic syn_fdset.txt syn_rc.txt synthetic_ec "$SYNTHETIC_EC_SOLVERS"
run_task data/synthetic syn_fdset.txt syn_rc.txt synthetic_pairwise "$SYNTHETIC_PAIRWISE_SOLVERS" lt100k

echo "Exact reproduction matrix finished: ${RESULT_ROOT}"
