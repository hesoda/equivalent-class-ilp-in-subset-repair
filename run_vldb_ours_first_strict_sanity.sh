#!/usr/bin/env bash
set -uo pipefail

# Prioritized strict-sanity rerun script.
# Goal: finish the paper's own algorithms first, then optionally run baselines.
# - Own exact algorithm: equiv_class_ilp
# - Own approximation algorithm: cc_lp
# - Uses timestamped result roots, separate from run_vldb_strict_sanity_experiments.sh.
# - Passes --strict_sanity. In current driver.py this checks FD consistency only;
#   RC is still reported but does not fail subset-repair sanity.
# - Runs one solver/relation per Python process.
# - Sorts CSVs by numeric size/noise.
# - Optional baseline phase is disabled by default.

BASE_DIR="${BASE_DIR:-/home/yuanlin/RS-repair/RS-repair}"
PYTHON_BIN="${PYTHON_BIN:-${BASE_DIR}/.conda/bin/python}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RESULT_ROOT="${RESULT_ROOT:-${BASE_DIR}/result/vldb_ours_first_strict_sanity/${RUN_ID}}"
STATUS_FILE="${RESULT_ROOT}/run_status.tsv"
FORCE="${FORCE:-0}"

# Phase controls.
RUN_OURS="${RUN_OURS:-1}"
RUN_BASELINES="${RUN_BASELINES:-0}"
INCLUDE_HOSPITAL="${INCLUDE_HOSPITAL:-0}"

# Solver groups.
OURS_EXACT_SOLVERS="${OURS_EXACT_SOLVERS:-equiv_class_ilp}"
OURS_APPROX_SOLVERS="${OURS_APPROX_SOLVERS:-cc_lp}"
SMOKE_SOLVERS="${SMOKE_SOLVERS:-equiv_class_ilp,cc_lp}"

# Optional second phase. Kept off by default because these dominate runtime/OOM risk.
BASELINE_REAL_EXACT_SOLVERS="${BASELINE_REAL_EXACT_SOLVERS:-ilp_baseline}"
BASELINE_REAL_APPROX_SOLVERS="${BASELINE_REAL_APPROX_SOLVERS:-te_lp}"
BASELINE_SYNTHETIC_RISKY_SOLVERS="${BASELINE_SYNTHETIC_RISKY_SOLVERS:-vc_approx_baseline,ilp_baseline,te_lp}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="python3"
fi

mkdir -p "${RESULT_ROOT}"
printf 'timestamp\tphase\tsuite\tdataset\trelation\tsolver\tstatus\texit_code\tlog\n' > "${STATUS_FILE}"

ts_now() {
    date +%Y-%m-%dT%H:%M:%S%z
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

run_one() {
    local phase="$1" suite="$2" dataset="$3" input_subdir="$4" fdset="$5" rc="$6" relation="$7" solver="$8"
    local input_dir="${BASE_DIR}/${input_subdir%/}/"
    local result_dir="${RESULT_ROOT}/${phase}/${suite}/${dataset}/"
    local relation_name="${relation%.csv}"
    local out_file="${result_dir}${relation}_${solver}.txt"
    local log_file="${result_dir}${relation_name}_${solver}_execution.log"

    mkdir -p "${result_dir}"

    if [[ -e "${out_file}" && "${FORCE}" != "1" ]]; then
        echo "[skip] ${phase}/${suite}/${dataset}/${relation}/${solver}: output exists"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${phase}" "${suite}" "${dataset}" "${relation}" "${solver}" "skip_exists" "0" "${log_file}" >> "${STATUS_FILE}"
        return 0
    fi

    echo "======================================================================"
    echo "[phase]   ${phase}"
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
        echo "[ok] ${phase}/${suite}/${dataset}/${relation}/${solver}"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${phase}" "${suite}" "${dataset}" "${relation}" "${solver}" "ok" "${code}" "${log_file}" >> "${STATUS_FILE}"
    else
        echo "[fail] ${phase}/${suite}/${dataset}/${relation}/${solver}, exit=${code}"
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${phase}" "${suite}" "${dataset}" "${relation}" "${solver}" "fail" "${code}" "${log_file}" >> "${STATUS_FILE}"
    fi
    return "${code}"
}

run_all_sizes() {
    local phase="$1" suite="$2" dataset="$3" input_subdir="$4" fdset="$5" rc="$6" solvers_csv="$7"
    local input_dir="${BASE_DIR}/${input_subdir%/}/"
    local relations=()
    mapfile -t relations < <(list_csv_sorted "${input_dir}")
    IFS=',' read -r -a solvers <<< "${solvers_csv}"

    for relation in "${relations[@]}"; do
        for solver in "${solvers[@]}"; do
            run_one "${phase}" "${suite}" "${dataset}" "${input_subdir}" "${fdset}" "${rc}" "${relation}" "${solver}" || true
        done
    done
}

run_truncate_after_failure() {
    local phase="$1" suite="$2" dataset="$3" input_subdir="$4" fdset="$5" rc="$6" solvers_csv="$7"
    local input_dir="${BASE_DIR}/${input_subdir%/}/"
    local relations=()
    mapfile -t relations < <(list_csv_sorted "${input_dir}")
    IFS=',' read -r -a solvers <<< "${solvers_csv}"

    for solver in "${solvers[@]}"; do
        local stopped=0
        for relation in "${relations[@]}"; do
            if [[ ${stopped} -eq 1 ]]; then
                local result_dir="${RESULT_ROOT}/${phase}/${suite}/${dataset}/"
                local log_file="${result_dir}${relation%.csv}_${solver}_execution.log"
                mkdir -p "${result_dir}"
                echo "[truncate] ${phase}/${suite}/${dataset}/${relation}/${solver}: previous smaller size failed"
                printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(ts_now)" "${phase}" "${suite}" "${dataset}" "${relation}" "${solver}" "truncated_after_failure" "0" "${log_file}" >> "${STATUS_FILE}"
                continue
            fi
            run_one "${phase}" "${suite}" "${dataset}" "${input_subdir}" "${fdset}" "${rc}" "${relation}" "${solver}"
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
        run_one "00_smoke" "smoke" "comb" "data/comb" "fdset.txt" "rc.txt" "30_0.5_dirty.csv" "${solver}" || true
    done
}

run_main_real_ours() {
    run_all_sizes "01_ours_first" "real_exact" "acs_chain" "data/input_data_acs/chain_FD" "chain_fdset.txt" "REGION_rc.txt" "${OURS_EXACT_SOLVERS}"
    run_all_sizes "01_ours_first" "real_exact" "acs_nonchain" "data/input_data_acs/non_chain_FD" "non_chain_fdset.txt" "NATIVITY_rc.txt" "${OURS_EXACT_SOLVERS}"
    run_all_sizes "01_ours_first" "real_exact" "compas_chain" "data/input_data_compas/chain_FD" "chain_fdset.txt" "SEX_rc.txt" "${OURS_EXACT_SOLVERS}"
    run_all_sizes "01_ours_first" "real_exact" "compas_nonchain" "data/input_data_compas/non_chain_FD" "non_chain_fdset.txt" "SEX_rc.txt" "${OURS_EXACT_SOLVERS}"

    run_all_sizes "01_ours_first" "real_approx" "acs_chain" "data/input_data_acs/chain_FD" "chain_fdset.txt" "REGION_rc.txt" "${OURS_APPROX_SOLVERS}"
    run_all_sizes "01_ours_first" "real_approx" "acs_nonchain" "data/input_data_acs/non_chain_FD" "non_chain_fdset.txt" "NATIVITY_rc.txt" "${OURS_APPROX_SOLVERS}"
    run_all_sizes "01_ours_first" "real_approx" "compas_chain" "data/input_data_compas/chain_FD" "chain_fdset.txt" "SEX_rc.txt" "${OURS_APPROX_SOLVERS}"
    run_all_sizes "01_ours_first" "real_approx" "compas_nonchain" "data/input_data_compas/non_chain_FD" "non_chain_fdset.txt" "SEX_rc.txt" "${OURS_APPROX_SOLVERS}"
}

run_main_synthetic_ours() {
    run_all_sizes "01_ours_first" "synthetic_exact" "synthetic" "data/synthetic" "syn_fdset.txt" "syn_rc.txt" "${OURS_EXACT_SOLVERS}"
    run_all_sizes "01_ours_first" "synthetic_approx" "synthetic" "data/synthetic" "syn_fdset.txt" "syn_rc.txt" "${OURS_APPROX_SOLVERS}"
}

run_hospital_ours_if_requested() {
    if [[ "${INCLUDE_HOSPITAL}" != "1" ]]; then
        return 0
    fi
    run_all_sizes "01_ours_first" "hospital_exact" "hospital" "data/hospital" "hospital_fdset.txt" "hospital_rc.txt" "${OURS_EXACT_SOLVERS}"
    run_all_sizes "01_ours_first" "hospital_approx" "hospital" "data/hospital" "hospital_fdset.txt" "hospital_rc.txt" "${OURS_APPROX_SOLVERS}"
}

run_baselines_if_requested() {
    if [[ "${RUN_BASELINES}" != "1" ]]; then
        echo "[info] Baseline phase disabled. Set RUN_BASELINES=1 to run it after own algorithms."
        return 0
    fi

    run_all_sizes "02_baselines" "real_exact" "acs_chain" "data/input_data_acs/chain_FD" "chain_fdset.txt" "REGION_rc.txt" "${BASELINE_REAL_EXACT_SOLVERS}"
    run_all_sizes "02_baselines" "real_exact" "acs_nonchain" "data/input_data_acs/non_chain_FD" "non_chain_fdset.txt" "NATIVITY_rc.txt" "${BASELINE_REAL_EXACT_SOLVERS}"
    run_all_sizes "02_baselines" "real_exact" "compas_chain" "data/input_data_compas/chain_FD" "chain_fdset.txt" "SEX_rc.txt" "${BASELINE_REAL_EXACT_SOLVERS}"
    run_all_sizes "02_baselines" "real_exact" "compas_nonchain" "data/input_data_compas/non_chain_FD" "non_chain_fdset.txt" "SEX_rc.txt" "${BASELINE_REAL_EXACT_SOLVERS}"

    run_all_sizes "02_baselines" "real_approx" "acs_chain" "data/input_data_acs/chain_FD" "chain_fdset.txt" "REGION_rc.txt" "${BASELINE_REAL_APPROX_SOLVERS}"
    run_all_sizes "02_baselines" "real_approx" "acs_nonchain" "data/input_data_acs/non_chain_FD" "non_chain_fdset.txt" "NATIVITY_rc.txt" "${BASELINE_REAL_APPROX_SOLVERS}"
    run_all_sizes "02_baselines" "real_approx" "compas_chain" "data/input_data_compas/chain_FD" "chain_fdset.txt" "SEX_rc.txt" "${BASELINE_REAL_APPROX_SOLVERS}"
    run_all_sizes "02_baselines" "real_approx" "compas_nonchain" "data/input_data_compas/non_chain_FD" "non_chain_fdset.txt" "SEX_rc.txt" "${BASELINE_REAL_APPROX_SOLVERS}"

    run_truncate_after_failure "02_baselines" "synthetic_risky" "synthetic" "data/synthetic" "syn_fdset.txt" "syn_rc.txt" "${BASELINE_SYNTHETIC_RISKY_SOLVERS}"
}

echo "Run id: ${RUN_ID}"
echo "Result root: ${RESULT_ROOT}"
echo "Status file: ${STATUS_FILE}"
echo "Python: ${PYTHON_BIN}"
echo "RUN_OURS=${RUN_OURS}; RUN_BASELINES=${RUN_BASELINES}; INCLUDE_HOSPITAL=${INCLUDE_HOSPITAL}"

run_smoke

if [[ "${RUN_OURS}" == "1" ]]; then
    run_main_real_ours
    run_main_synthetic_ours
    run_hospital_ours_if_requested
else
    echo "[info] Own-algorithm phase disabled by RUN_OURS=0."
fi

run_baselines_if_requested

echo "Finished. Result root: ${RESULT_ROOT}"
echo "Status file: ${STATUS_FILE}"
