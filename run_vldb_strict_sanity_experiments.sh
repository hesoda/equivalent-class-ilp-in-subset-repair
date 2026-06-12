#!/usr/bin/env bash
set -uo pipefail

# Long-running VLDB experiment rerun script.
# - Uses timestamped result roots so existing result/ files are untouched.
# - Passes --strict_sanity. In driver.py this is FD-only sanity; RC is reported but not enforced.
# - Runs one solver/relation per Python process.
# - Sorts CSVs by numeric size/noise instead of filename order.
# - For synthetic risky solvers, stops larger sizes after the first failure.

BASE_DIR="${BASE_DIR:-/home/yuanlin/RS-repair/RS-repair}"
PYTHON_BIN="${PYTHON_BIN:-${BASE_DIR}/.conda/bin/python}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${RESULT_ROOT:-${BASE_DIR}/result/vldb_strict_sanity/${RUN_ID}}"
STATUS_FILE="${RESULT_ROOT}/run_status.tsv"

SMOKE_SOLVERS="${SMOKE_SOLVERS:-cc_lp,te_lp,et_te_lp}"
REAL_EXACT_SOLVERS="${REAL_EXACT_SOLVERS:-ilp_baseline,equiv_class_ilp}"
REAL_APPROX_SOLVERS="${REAL_APPROX_SOLVERS:-cc_lp,te_lp}"
SYNTHETIC_SAFE_SOLVERS="${SYNTHETIC_SAFE_SOLVERS:-equiv_class_ilp,cc_lp}"
SYNTHETIC_RISKY_SOLVERS="${SYNTHETIC_RISKY_SOLVERS:-vc_approx_baseline,ilp_baseline,te_lp}"
FORCE="${FORCE:-0}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="python3"
fi

mkdir -p "${RESULT_ROOT}"
printf 'timestamp\tsuite\tdataset\trelation\tsolver\tstatus\texit_code\tlog\n' > "${STATUS_FILE}"

ts_now() {
    date +%Y-%m-%dT%H:%M:%S%z
}

csv_size_key() {
    "${PYTHON_BIN}" - "$1" <<'PY'
import os, re, sys
name = os.path.basename(sys.argv[1])
m = re.match(r"(\d+)(?:_([0-9.]+))?", name)
size = int(m.group(1)) if m else 0
noise = float(m.group(2)) if m and m.group(2) is not None else 0.0
print(f"{size:012d}\t{noise:010.6f}\t{name}")
PY
}

list_csv_sorted() {
    local input_dir="$1"
    "${PYTHON_BIN}" - "${input_dir}" <<'PY'
import glob, os, re, sys
input_dir = sys.argv[1]
items = []
for path in glob.glob(os.path.join(input_dir, "*.csv")):
    name = os.path.basename(path)
    m = re.match(r"(\d+)(?:_([0-9.]+))?", name)
    size = int(m.group(1)) if m else 0
    noise = float(m.group(2)) if m and m.group(2) is not None else 0.0
    items.append((size, noise, name))
for _, _, name in sorted(items):
    print(name)
PY
}

relation_size() {
    "${PYTHON_BIN}" - "$1" <<'PY'
import os, re, sys
m = re.match(r"(\d+)", os.path.basename(sys.argv[1]))
print(int(m.group(1)) if m else 0)
PY
}

run_one() {
    local suite="$1" dataset="$2" input_subdir="$3" fdset="$4" rc="$5" relation="$6" solver="$7"
    local input_dir="${BASE_DIR}/${input_subdir%/}/"
    local result_dir="${RESULT_ROOT}/${suite}/${dataset}/"
    local relation_name="${relation%.csv}"
    local out_file="${result_dir}${relation}_${solver}.txt"
    local log_file="${result_dir}${relation_name}_${solver}_execution.log"

    mkdir -p "${result_dir}"

    if [[ -e "${out_file}" && "${FORCE}" != "1" ]]; then
        echo "[skip] ${suite}/${dataset}/${relation}/${solver}: output exists"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${suite}" "${dataset}" "${relation}" "${solver}" "skip_exists" "0" "${log_file}" >> "${STATUS_FILE}"
        return 0
    fi

    echo "======================================================================"
    echo "[suite]   ${suite}"
    echo "[dataset] ${dataset}"
    echo "[relation] ${relation}"
    echo "[solver]  ${solver}"
    echo "[result]  ${out_file}"
    echo "[log]     ${log_file}"
    echo "======================================================================"

    "${PYTHON_BIN}" "${BASE_DIR}/src/driver.py" \
        --input_dir "${input_dir}" \
        --result_dir "${result_dir}" \
        --relation "${relation}" \
        --fdset "${fdset}" \
        --rc "${rc}" \
        --solvers "${solver}" \
        --strict_sanity > "${log_file}" 2>&1

    local code=$?
    if [[ ${code} -eq 0 ]]; then
        echo "[ok] ${suite}/${dataset}/${relation}/${solver}"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${suite}" "${dataset}" "${relation}" "${solver}" "ok" "${code}" "${log_file}" >> "${STATUS_FILE}"
    else
        echo "[fail] ${suite}/${dataset}/${relation}/${solver}, exit=${code}"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${suite}" "${dataset}" "${relation}" "${solver}" "fail" "${code}" "${log_file}" >> "${STATUS_FILE}"
    fi
    return "${code}"
}

run_solver_list_all_sizes() {
    local suite="$1" dataset="$2" input_subdir="$3" fdset="$4" rc="$5" solvers_csv="$6"
    local input_dir="${BASE_DIR}/${input_subdir%/}/"
    local relations=()
    mapfile -t relations < <(list_csv_sorted "${input_dir}")
    IFS=',' read -r -a solvers <<< "${solvers_csv}"

    for relation in "${relations[@]}"; do
        for solver in "${solvers[@]}"; do
            run_one "${suite}" "${dataset}" "${input_subdir}" "${fdset}" "${rc}" "${relation}" "${solver}" || true
        done
    done
}

run_solver_list_truncate_on_failure() {
    local suite="$1" dataset="$2" input_subdir="$3" fdset="$4" rc="$5" solvers_csv="$6"
    local input_dir="${BASE_DIR}/${input_subdir%/}/"
    local relations=()
    mapfile -t relations < <(list_csv_sorted "${input_dir}")
    IFS=',' read -r -a solvers <<< "${solvers_csv}"

    for solver in "${solvers[@]}"; do
        local stopped=0
        for relation in "${relations[@]}"; do
            if [[ ${stopped} -eq 1 ]]; then
                local result_dir="${RESULT_ROOT}/${suite}/${dataset}/"
                local log_file="${result_dir}${relation%.csv}_${solver}_execution.log"
                mkdir -p "${result_dir}"
                echo "[truncate] ${suite}/${dataset}/${relation}/${solver}: previous smaller size failed"
                printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${suite}" "${dataset}" "${relation}" "${solver}" "truncated_after_failure" "0" "${log_file}" >> "${STATUS_FILE}"
                continue
            fi
            run_one "${suite}" "${dataset}" "${input_subdir}" "${fdset}" "${rc}" "${relation}" "${solver}"
            local code=$?
            if [[ ${code} -ne 0 ]]; then
                stopped=1
            fi
        done
    done
}

run_smoke() {
    IFS=',' read -r -a solvers <<< "${SMOKE_SOLVERS}"
    for solver in "${solvers[@]}"; do
        run_one "00_smoke" "comb" "data/comb" "fdset.txt" "rc.txt" "30_0.5_dirty.csv" "${solver}" || true
    done
}

summarize_if_available() {
    if [[ -f "${BASE_DIR}/summarize_cc_te_quality.py" ]]; then
        "${PYTHON_BIN}" "${BASE_DIR}/summarize_cc_te_quality.py" "${RESULT_ROOT}/02_real_approx" --output "${RESULT_ROOT}/02_real_approx/cc_te_lp_quality_summary.csv" || true
    fi
}

echo "Run id: ${RUN_ID}"
echo "Result root: ${RESULT_ROOT}"
echo "Status file: ${STATUS_FILE}"
echo "Python: ${PYTHON_BIN}"

run_smoke

run_solver_list_all_sizes "01_real_exact" "acs_chain" "data/input_data_acs/chain_FD" "chain_fdset.txt" "REGION_rc.txt" "${REAL_EXACT_SOLVERS}"
run_solver_list_all_sizes "01_real_exact" "acs_nonchain" "data/input_data_acs/non_chain_FD" "non_chain_fdset.txt" "NATIVITY_rc.txt" "${REAL_EXACT_SOLVERS}"
run_solver_list_all_sizes "01_real_exact" "compas_chain" "data/input_data_compas/chain_FD" "chain_fdset.txt" "SEX_rc.txt" "${REAL_EXACT_SOLVERS}"
run_solver_list_all_sizes "01_real_exact" "compas_nonchain" "data/input_data_compas/non_chain_FD" "non_chain_fdset.txt" "SEX_rc.txt" "${REAL_EXACT_SOLVERS}"

run_solver_list_all_sizes "02_real_approx" "acs_chain" "data/input_data_acs/chain_FD" "chain_fdset.txt" "REGION_rc.txt" "${REAL_APPROX_SOLVERS}"
run_solver_list_all_sizes "02_real_approx" "acs_nonchain" "data/input_data_acs/non_chain_FD" "non_chain_fdset.txt" "NATIVITY_rc.txt" "${REAL_APPROX_SOLVERS}"
run_solver_list_all_sizes "02_real_approx" "compas_chain" "data/input_data_compas/chain_FD" "chain_fdset.txt" "SEX_rc.txt" "${REAL_APPROX_SOLVERS}"
run_solver_list_all_sizes "02_real_approx" "compas_nonchain" "data/input_data_compas/non_chain_FD" "non_chain_fdset.txt" "SEX_rc.txt" "${REAL_APPROX_SOLVERS}"

run_solver_list_all_sizes "03_synthetic_safe" "synthetic" "data/synthetic" "syn_fdset.txt" "syn_rc.txt" "${SYNTHETIC_SAFE_SOLVERS}"
run_solver_list_truncate_on_failure "04_synthetic_risky" "synthetic" "data/synthetic" "syn_fdset.txt" "syn_rc.txt" "${SYNTHETIC_RISKY_SOLVERS}"

summarize_if_available

echo "Finished. Result root: ${RESULT_ROOT}"
echo "Status file: ${STATUS_FILE}"
