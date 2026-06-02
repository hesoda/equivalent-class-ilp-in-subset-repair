from table import Table
from functional_dependency import load_fdset
from representative_constraint import load_representative_constraint
from reduction import (
    s_repair,
    s_repair_wo_rc,
    AfterReduction,
    AfterReduction_wo_rc,
)
from exact import (
    exact,
    exact_by_grb_ilp_wo_rc,
    partition_and_solve_ilp,
    exact_by_grb_ilp_equiv_class,
    relax_lp_baseline,
    relax_lp_equiv_class,
    exact_by_grb_ilp_equiv_class_rc,
    exact_by_grb_ilp_with_yannakakis_ef,
    exact_by_grb_ilp_wo_rc_opt,
    exact_by_grb_ilp_clique_enhanced
)
from approx import approx
from time import time
import numpy as np
from utility import sanity_check, compute_pairwise_violations, compute_violated_tuples
import warnings
from postclean import postclean_for_set

warnings.filterwarnings("ignore")

import argparse

import resource


def run_with_profiler(func, *args, **kwargs):
    # 记录执行前的系统资源状态
    start_time = time()
    
    # 执行你的算法
    result = func(*args, **kwargs)
    
    # 记录执行后的状态
    end_time = time()
    
    # 获取当前进程的资源使用情况
    # ru_maxrss 在 Linux 上返回的是 KB (千字节)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_ram_mb = usage.ru_maxrss / 1024.0
    
    print(f"Time: {end_time - start_time:.4f}s | True OS Peak RAM: {peak_ram_mb:.2f} MB")
    
    return result


def load_data(table_filename, fds_filename, rc_filename):
    representative_column, rc = load_representative_constraint(rc_filename)
    t = Table(
        representative_column, filename=table_filename, delimeter=",", dropna=False
    )
    rc.set_labels(t.labels)
    delta = load_fdset(fds_filename, t)
    for col in delta.get_all_cols():
        if t.missing_cnt[col] > 0:
            raise ValueError(f"Missing values in column: {col}")
    return t, delta, rc


def solve(t, delta, rc, res_dir, solver=[], prefix="default", seed=None, report_violation=False):
    for func_name in solver:
        with open(res_dir + prefix + "_" + func_name + ".txt", "w") as fout:
            start_ts = time()
            repairs, optimal_srepair = None, None
            match func_name:
                case "lhschain_dp":
                    repairs = s_repair(
                        t, delta, rc, matching_method="GRB_ILP", seed=seed
                    )
                case "globalilp":
                    repairs = run_with_profiler(exact, t, delta, rc, seed=seed)
                case "lp_greedyrounding":
                    repairs = approx(t, delta, rc, "GRB_LP_GREEDY_ROUNDING", seed=seed)
                case "lp_reprrounding":
                    repairs = approx(
                        t, delta, rc, "GRB_LP_NEW_GREEDY_ROUNDING", seed=seed
                    )
                case "cc_lp":
                    repairs = run_with_profiler(
                        approx, t, delta, rc, method="CC_LP", seed=seed
                    )
                case "te_lp":
                    repairs = run_with_profiler(
                        approx, t, delta, rc, method="TE_LP", seed=seed
                    )
                case "et_te_lp":
                    repairs = run_with_profiler(
                        approx, t, delta, rc, method="ET_TE_LP", seed=seed
                    )
                case "fdcleanser":
                    repairs = run_with_profiler(s_repair,
                        t, delta, rc, AfterReduction.MOST_FREQUENT_COL, seed=seed
                    )
                case "dp_baseline":
                    optimal_srepair = s_repair_wo_rc(
                        t, delta, AfterReduction_wo_rc.ERROR, seed=seed
                    )
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                case "vc_approx_baseline":
                    optimal_srepair = run_with_profiler(s_repair_wo_rc,
                        t, delta, AfterReduction_wo_rc.APPROX, seed=seed
                    )
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                case "ilp_baseline":
                    # 用 run_with_profiler 把原函数套起来
                    optimal_srepair = run_with_profiler(exact_by_grb_ilp_wo_rc, t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                    
                case "ilp_baseline_wo_opt":
                    # 用 run_with_profiler 把原函数套起来
                    optimal_srepair = run_with_profiler(exact_by_grb_ilp_wo_rc_opt, t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                case "clique_baseline_wo_opt":
                    # 用 run_with_profiler 把原函数套起来
                    optimal_srepair = run_with_profiler(exact_by_grb_ilp_clique_enhanced, t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}

                case "ilp_baseline_plus_odd_holes_wo_opt":
                    # 用 run_with_profiler 把原函数套起来
                    optimal_srepair = run_with_profiler(exact_by_grb_ilp_with_yannakakis_ef, t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                    
                case "partition_ilp":
                    optimal_srepair = run_with_profiler(partition_and_solve_ilp, t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                    
                case "equiv_class_ilp_rc":
                    optimal_srepair = run_with_profiler(exact_by_grb_ilp_equiv_class_rc, t, delta,rc, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}

                case "equiv_class_ilp":
                    optimal_srepair = run_with_profiler(exact_by_grb_ilp_equiv_class, t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                case "relax_lp_baseline":
                    optimal_srepair = relax_lp_baseline(t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                case "relax_lp_equiv_class":   
                    optimal_srepair = relax_lp_equiv_class(t, delta, seed=seed)
                    repairs = {optimal_srepair.color_distribution: optimal_srepair}
                case default:
                    raise ValueError("Unsupported Solver")
            # postclean_ts = time()
            optimal = postclean_for_set(repairs, rc)
            end_ts = time()
            # assert sanity_check(optimal, delta, rc)
            fout.write(f"Overall Time cost(in secs.): {end_ts - start_ts}\n")
            # fout.write(f"Size of RS-repair: {optimal.nrows()}\n")
            # if report_violation:
            #     fout.write(
            #         f"Pairwise Violation Ratio: {np.round(100. * compute_pairwise_violations(optimal, delta) / optimal.npairs(), 3) if optimal.nrows() > 0 else 0}%\n"
            #     )
            #     fout.write(
            #         f"Percentage of Violated Tuples: {np.round(100. * compute_violated_tuples(optimal, delta) / optimal.nrows(), 3) if optimal.nrows() > 0 else 0}%\n"
            #     )
            # fout.write(
            #     f"Distribution of Representative Column : {optimal.get_representative_column_distribution()}\n"
            # )
            # fout.write(f"Time cost of PostClean(in secs.): {end_ts - postclean_ts}\n")
            # fout.write(str(optimal) + "\n")
            # print(
            #     f"[{np.round(end_ts - start_ts, 3)}s] Size of RS-repair({func_name}): {optimal.nrows()}"
            # )
            if optimal_srepair is not None:
                with open(
                    res_dir + "[before-postclean]" + prefix + "_" + func_name + ".txt", "w"
                ) as fbackup:
                    fbackup.write(
                        f"Distribution of Representative Column : {optimal_srepair.get_representative_column_distribution()}\n"
                    )
                    fbackup.write(str(optimal_srepair) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input_dir",
        type=str,
        default="../data/example/",
        help="the (related) input directory",
    )
    parser.add_argument(
        "--result_dir",
        type=str,
        default="../result/example/",
        help="the (related) output directory",
    )
    parser.add_argument(
        "--relation",
        type=str,
        default="example_relation.txt",
        help="the filename of input relation",
    )
    parser.add_argument(
        "--fdset", type=str, default="example_fdset.txt", help="the filename of fdset"
    )
    parser.add_argument(
        "--rc", type=str, default="example_rc.txt", help="the filename of RC"
    )
    parser.add_argument(
        "--solvers",
        type=str,
        default="globailp",
        help="comma-separated list of solvers, [lhschain_dp,globalilp,lp_greedyrounding,lp_reprrounding,cc_lp,te_lp,et_te_lp,fdcleanser,dp_baseline,vc_approx_baseline,ilp_baseline]",
    )
    parser.add_argument(
        "--report_violation",
        action="store_true",
        default=False,
        help="(Optional) report the violations (in terms of FDs) of the tuples retained by the RS-repair",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="(Optional) the random seed"
    )
    args = parser.parse_args()
    dir = args.input_dir
    res_dir = args.result_dir
    t_filename = dir + args.relation
    fds_filename = dir + args.fdset
    rc_filename = dir + args.rc
    solvers = args.solvers.split(",")
    report_violation = args.report_violation
    seed = args.seed

    t, delta, rc = load_data(t_filename, fds_filename, rc_filename)

    for single_solver in solvers:
        print("Working on solver:", single_solver)
        solve(
            t,
            delta,
            rc,
            res_dir,
            solver=[single_solver],
            prefix=args.relation,
            seed=seed,
            report_violation=report_violation,
        )
        print("Finished!")
