import gurobipy as gb
from gurobipy import GRB
from table import Table
import numpy as np
from utility import global_random_seed, eps
from color_distribution import ColorDistribution
import copy


def approx(t, delta, rc, method="GRB_LP_ROUNDING", seed=None):
    if method in [
        "GRB_LP_ROUNDING",
        "GRB_LP_GREEDY_ROUNDING",
        "GRB_LP_NEW_GREEDY_ROUNDING",
    ]:
        return approx_by_grb_lp_rounding(
            t, delta, rc, rounding_method=method[4:], seed=seed
        )
    elif method == "CC_LP": # <-- 补充 CC-LP 路由分支
        return cc_lp_approx(t, delta, rc, seed=seed)
    elif method == "TE_LP":
        return te_lp_approx(t, delta, seed=seed)
    elif method == "ET_TE_LP":
        return et_te_lp_approx(t, delta, seed=seed)
        
    raise ValueError("Not Supported Optimizer")


def approx_by_grb_lp_rounding(t, delta, rc, rounding_method, seed):
    # initialize the candidate set as a singleton set with the emptyset as a trivial repair
    map = {t.get_empty_table().color_distribution: t.get_empty_table()}

    m = gb.Model()
    if seed is not None:
        m.Params.Seed = seed
    x = []

    for i in range(t.df.shape[0]):
        x.append(m.addVar(lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name=f"r{i}"))

    added = {}
    edges = []
    # construct the constraints for FDs
    for fd in delta.fds:
        lhs_grouped = t.df.groupby(fd.lhs.cols)
        for _, lhs_idxs in lhs_grouped.groups.items():
            rhs_grouped = t.df.loc[lhs_idxs].groupby(fd.rhs.col)
            all_idxs = []
            for _, rhs_idxs in rhs_grouped.groups.items():
                all_idxs.append(rhs_idxs.tolist())
            for i in range(len(all_idxs)):
                for j in range(i + 1, len(all_idxs)):
                    for ii in all_idxs[i]:
                        for jj in all_idxs[j]:
                            if (ii, jj) not in added and (jj, ii) not in added:
                                m.addConstr(x[ii] + x[jj] <= 1)
                                added[(ii, jj)] = 1
                                edges.append([ii, jj])

    # construct the constraints for RC
    for color in range(t.color_distribution.c):
        expr = gb.LinExpr()
        for idx, _ in t.df[t.df[t.representative_column] == color].iterrows():
            expr += x[idx]
        expr -= gb.quicksum(x) * rc.constraint[t.labels[color]]
        m.addLConstr(expr, GRB.GREATER_EQUAL, 0)

    m.setObjective(gb.quicksum(x), GRB.MAXIMIZE)
    m.Params.LogToConsole = 0
    m.optimize()

    assert m.status == GRB.OPTIMAL

    idxs = []

    if rounding_method == "LP_ROUNDING":
        # random rounding (deprecated because it might introduce FD violations during rounding)
        r = np.random.RandomState(seed=global_random_seed)
        for v in m.getVars():
            if v.VarName != "ans" and r.rand() <= v.X:
                idxs.append(int(v.VarName[1:]))
    elif rounding_method == "LP_GREEDY_ROUNDING":
        # greedyrounding
        n_colors = t.color_distribution.c
        ii = 0
        nodes = [[], []]
        for v in m.getVars():
            if v.VarName != "ans":
                if v.X == 1.0:
                    idxs.append(int(v.VarName[1:]))
                elif v.X > 0.0 and v.X < 1.0:
                    nodes[ii].append([int(v.VarName[1:]), v.X])

        adj = _compute_adj(edges)
        while len(nodes[ii]) > 0:
            id_to_pos = {}
            for i in range(len(nodes[ii])):
                id_to_pos[nodes[ii][i][0]] = i

            pick = None
            for i in range(len(nodes[ii])):
                if pick is None or len(adj[nodes[ii][i][0]]) < len(adj[pick]):
                    pick = nodes[ii][i][0]

            nodes[ii][id_to_pos[pick]][1] = 1.0
            for nxt in adj[pick]:
                if nxt in id_to_pos:
                    nodes[ii][id_to_pos[nxt]][1] = 0.0

            nodes[1 - ii].clear()

            for i in range(len(nodes[ii])):
                if nodes[ii][i][1] < 1.0 and nodes[ii][i][1] > 0.0:
                    nodes[1 - ii].append(copy.deepcopy(nodes[ii][i]))
                elif nodes[ii][i][1] == 1.0:
                    idxs.append(nodes[ii][i][0])
            ii = 1 - ii
    elif rounding_method == "LP_NEW_GREEDY_ROUNDING":
        # repr rounding
        n_colors = t.color_distribution.c
        ii = 0
        nodes = [[], []]
        for v in m.getVars():
            if v.VarName != "ans":
                if v.X == 1.0:
                    idxs.append(int(v.VarName[1:]))
                elif v.X > 0.0 and v.X < 1.0:
                    nodes[ii].append([int(v.VarName[1:]), v.X])

        strata_to_cnt = {}
        for color in range(t.color_distribution.c):
            strata_to_cnt[color] = 0

        adj = _compute_adj(edges)
        while len(nodes[ii]) > 0:
            id_to_pos = {}
            for i in range(len(nodes[ii])):
                id_to_pos[nodes[ii][i][0]] = i

            pick = None
            pick_color = None
            for i in range(len(nodes[ii])):
                x = nodes[ii][i][0]
                x_color = t.df.loc[x, t.representative_column].item()
                if pick is None:
                    pick = x
                    pick_color = x_color
                else:
                    x_color_constraint = rc.constraint[rc.labels[x_color]]
                    pick_color_constraint = rc.constraint[rc.labels[pick_color]]
                    x_ratio = strata_to_cnt[x_color] / x_color_constraint
                    pick_ratio = strata_to_cnt[pick_color] / pick_color_constraint
                    if (x_ratio, x_color_constraint, len(adj[x])) < (
                        pick_ratio,
                        pick_color_constraint,
                        len(adj[pick]),
                    ):
                        pick = x
                        pick_color = x_color

            assert pick is not None
            strata_to_cnt[pick_color] += 1

            nodes[ii][id_to_pos[pick]][1] = 1.0
            for nxt in adj[pick]:
                if nxt in id_to_pos:
                    nodes[ii][id_to_pos[nxt]][1] = 0.0

            nodes[1 - ii].clear()

            for i in range(len(nodes[ii])):
                if nodes[ii][i][1] < 1.0 and nodes[ii][i][1] > 0.0:
                    nodes[1 - ii].append(copy.deepcopy(nodes[ii][i]))
                elif nodes[ii][i][1] == 1.0:
                    idxs.append(nodes[ii][i][0])
            ii = 1 - ii

    # get the S-repair according to the value of each variable
    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)
    map[t0.color_distribution] = t0
    return map


def _compute_adj(edges):
    adj = {}
    for id in range(len(edges)):
        if edges[id][0] not in adj:
            adj[edges[id][0]] = []
        if edges[id][1] not in adj:
            adj[edges[id][1]] = []
        adj[edges[id][0]].append(edges[id][1])
        adj[edges[id][1]].append(edges[id][0])
    return adj


# ==========================================
# TE-LP / et-TE-LP Baselines (Miao et al.)
# ==========================================

def _normalize_lp_value(val, half_eps=1e-6):
    if val <= eps:
        return 0.0
    if abs(val - 0.5) <= half_eps:
        return 0.5
    if val >= 1.0 - eps:
        return 1.0
    return val


def _build_conflict_edges_for_active(t, delta, active_tids):
    edges = set()
    if not active_tids:
        return []

    sub_df = t.df.loc[active_tids]

    for fd in delta.fds:
        if len(fd.lhs.cols) == 0:
            lhs_groups = {("dummy_lhs",): sub_df.index.tolist()}
        else:
            lhs_groups = sub_df.groupby(fd.lhs.cols).groups

        for _, lhs_idxs in lhs_groups.items():
            rhs_grouped = sub_df.loc[lhs_idxs].groupby(fd.rhs.col)
            rhs_groups = [rhs_idxs.tolist() for _, rhs_idxs in rhs_grouped.groups.items()]

            for i in range(len(rhs_groups)):
                for j in range(i + 1, len(rhs_groups)):
                    for ii in rhs_groups[i]:
                        for jj in rhs_groups[j]:
                            u, v = (ii, jj) if ii < jj else (jj, ii)
                            edges.add((u, v))
    return list(edges)


def _find_triad_same_fd(t, delta, active_set, residual_weight):
    if not active_set:
        return None

    sub_df = t.df.loc[list(active_set)]

    for fd in delta.fds:
        if len(fd.lhs.cols) == 0:
            lhs_groups = {("dummy_lhs",): sub_df.index.tolist()}
        else:
            lhs_groups = sub_df.groupby(fd.lhs.cols).groups

        for _, lhs_idxs in lhs_groups.items():
            rhs_grouped = sub_df.loc[lhs_idxs].groupby(fd.rhs.col)
            picked = []
            for _, rhs_idxs in rhs_grouped.groups.items():
                chosen_tid = None
                for tid in rhs_idxs:
                    if residual_weight.get(tid, 0.0) > eps:
                        chosen_tid = tid
                        break
                if chosen_tid is not None:
                    picked.append(chosen_tid)
                if len(picked) >= 3:
                    return picked[0], picked[1], picked[2]
    return None


def _trim_instance_te_lp(t, delta, active_tids, orig_weights):
    residual_weight = {tid: orig_weights[tid] for tid in active_tids}
    active_set = set(active_tids)

    while True:
        triad = _find_triad_same_fd(t, delta, active_set, residual_weight)
        if triad is None:
            break
        w_min = min(residual_weight[tid] for tid in triad)
        for tid in triad:
            residual_weight[tid] -= w_min
            if residual_weight[tid] <= eps:
                residual_weight[tid] = 0.0
                active_set.discard(tid)

    return active_set, residual_weight


def _find_sigma_partition(t, delta, active_tids):
    partitions = [set(active_tids)]
    df = t.df

    for fd in delta.fds:
        new_partitions = []
        for K in partitions:
            if not K:
                continue
            K1, K2 = set(), set()
            lhs_to_rhs = {}

            for tid in sorted(K):
                row = df.loc[tid]
                lhs_val = tuple(row[col] for col in fd.lhs.cols)
                rhs_val = row[fd.rhs.col]
                if lhs_val not in lhs_to_rhs or lhs_to_rhs[lhs_val] == rhs_val:
                    lhs_to_rhs[lhs_val] = rhs_val
                    K1.add(tid)
                else:
                    K2.add(tid)

            if K1:
                new_partitions.append(K1)
            if K2:
                new_partitions.append(K2)
        partitions = new_partitions

    return partitions


def _solve_bl_lp(t, delta, active_tids, residual_weight, seed=None):
    edges = _build_conflict_edges_for_active(t, delta, active_tids)

    m = gb.Model()
    if seed is not None:
        m.Params.Seed = seed
    m.Params.LogToConsole = 0

    x = m.addVars(active_tids, vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name="x")

    for u, v in edges:
        m.addConstr(x[u] + x[v] >= 1)

    obj = gb.quicksum(residual_weight[tid] * x[tid] for tid in active_tids)
    m.setObjective(obj, GRB.MINIMIZE)
    m.optimize()

    assert m.status == GRB.OPTIMAL

    x_vals = {tid: _normalize_lp_value(x[tid].X) for tid in active_tids}
    return x_vals


def _te_lp_keep_ids(t, delta, seed=None, active_tids=None, orig_weights=None):
    if active_tids is None:
        active_tids = list(range(t.nrows()))
    if orig_weights is None:
        orig_weights = {tid: 1.0 for tid in active_tids}

    active_set, residual_weight = _trim_instance_te_lp(
        t, delta, active_tids, orig_weights
    )
    active_list = sorted(active_set)
    if not active_list:
        return []

    partitions = _find_sigma_partition(t, delta, active_list)
    x_vals = _solve_bl_lp(t, delta, active_list, residual_weight, seed=seed)

    best_K = set()
    max_half_weight = -1.0
    for K in partitions:
        current_weight = sum(
            residual_weight[tid]
            for tid in K
            if abs(x_vals[tid] - 0.5) <= 1e-6
        )
        if current_weight > max_half_weight:
            max_half_weight = current_weight
            best_K = set(K)

    keep_idxs = []
    for tid in active_list:
        val = x_vals[tid]
        if val <= eps:
            keep_idxs.append(tid)
        elif abs(val - 0.5) <= 1e-6 and tid in best_K:
            keep_idxs.append(tid)

    return keep_idxs


def te_lp_approx(t, delta, seed=None):
    keep_idxs = _te_lp_keep_ids(t, delta, seed=seed)
    if not keep_idxs:
        empty_t = t.get_empty_table()
        return {empty_t.color_distribution: empty_t}

    t0 = Table(
        t.representative_column,
        t.df.iloc[keep_idxs].reset_index(drop=True),
        t.labels,
    )
    return {t0.color_distribution: t0}


def _eliminate_quasi_turan_clusters(t, delta, active_tids, orig_weights, h):
    sub_df = t.df.loc[active_tids]
    candidates = []

    for fd in delta.fds:
        if len(fd.lhs.cols) == 0:
            lhs_groups = {("dummy_lhs",): sub_df.index.tolist()}
        else:
            lhs_groups = sub_df.groupby(fd.lhs.cols).groups

        for lhs_val, lhs_idxs in lhs_groups.items():
            rhs_grouped = sub_df.loc[lhs_idxs].groupby(fd.rhs.col)
            if not rhs_grouped.groups:
                continue

            total_w = sum(orig_weights[tid] for tid in lhs_idxs)
            max_bucket = 0.0
            for _, rhs_idxs in rhs_grouped.groups.items():
                bucket_w = sum(orig_weights[tid] for tid in rhs_idxs)
                if bucket_w > max_bucket:
                    max_bucket = bucket_w

            if total_w >= (h + 1) * max_bucket:
                candidates.append(
                    {
                        "tuple_ids": set(lhs_idxs),
                        "total_weight": total_w,
                        "lhs_key": lhs_val,
                    }
                )

    candidates.sort(
        key=lambda c: (-c["total_weight"], len(c["tuple_ids"]), str(c["lhs_key"]))
    )

    eliminated = set()
    for c in candidates:
        if c["tuple_ids"].isdisjoint(eliminated):
            eliminated.update(c["tuple_ids"])

    return set(active_tids) - eliminated


def et_te_lp_approx(t, delta, seed=None, h_values=None):
    all_tids = list(range(t.nrows()))
    if not all_tids:
        empty_t = t.get_empty_table()
        return {empty_t.color_distribution: empty_t}

    orig_weights = {tid: 1.0 for tid in all_tids}

    if h_values is None:
        h_values = range(2, len(all_tids))
        if len(all_tids) < 3:
            h_values = []

    if not h_values:
        return te_lp_approx(t, delta, seed=seed)

    best_keep = []
    best_cost = float("inf")

    for h in h_values:
        active_set = _eliminate_quasi_turan_clusters(
            t, delta, all_tids, orig_weights, h
        )
        keep_idxs = _te_lp_keep_ids(
            t,
            delta,
            seed=seed,
            active_tids=sorted(active_set),
            orig_weights=orig_weights,
        )
        keep_set = set(keep_idxs)
        cost = sum(orig_weights[tid] for tid in all_tids if tid not in keep_set)

        if cost < best_cost:
            best_cost = cost
            best_keep = keep_idxs

    if not best_keep:
        empty_t = t.get_empty_table()
        return {empty_t.color_distribution: empty_t}

    t0 = Table(
        t.representative_column,
        t.df.iloc[sorted(best_keep)].reset_index(drop=True),
        t.labels,
    )
    return {t0.color_distribution: t0}


# ==========================================
# CC-LP (Conflict Clique LP) Algorithm Suite
# ==========================================

CC_LP_EPS = 1e-9


class CCLPState:
    def __init__(self, t: Table, delta):
        self.t = t
        self.delta = delta
        # Residual tuple mass used by CC-LP trimming and by the residual LP.
        self.tuples = {i: {'weight': 1.0, 'ec_refs': []} for i in range(t.nrows())}
        self.ecs = {}
        self.ccs = {}
        self._build_indices()

    def _build_indices(self):
        """Stage 0: Build tuple/EC/CC cross references for every FD."""
        ec_counter = 0
        cc_counter = 0
        df = self.t.df

        for fd_id, fd in enumerate(self.delta.fds):
            lhs_cols = fd.lhs.cols
            rhs_col = fd.rhs.col

            if len(lhs_cols) == 0:
                groups = {("dummy_lhs",): df.index.tolist()}
            else:
                grouped = df.groupby(lhs_cols)
                groups = grouped.groups

            for lhs_val, idxs in groups.items():
                cc_id = cc_counter
                cc_counter += 1
                self.ccs[cc_id] = {'fd_id': fd_id, 'lhs_val': lhs_val, 'ec_ids': []}

                sub_df = df.loc[idxs]
                rhs_grouped = sub_df.groupby(rhs_col)

                for rhs_val, ec_idxs in rhs_grouped.groups.items():
                    ec_id = ec_counter
                    ec_counter += 1
                    tuple_ids = ec_idxs.tolist()
                    weight = len(tuple_ids) * 1.0

                    self.ecs[ec_id] = {
                        'fd_id': fd_id,
                        'rhs_val': rhs_val,
                        'tuple_ids': tuple_ids,
                        'cc_id': cc_id,
                        'weight': weight,
                    }
                    self.ccs[cc_id]['ec_ids'].append(ec_id)

                    for tid in tuple_ids:
                        self.tuples[tid]['ec_refs'].append(ec_id)

    def get_active_ec_count(self, cc_id):
        return sum(
            1
            for eid in self.ccs[cc_id]['ec_ids']
            if self.ecs[eid]['weight'] > CC_LP_EPS
        )

    def _deduct_tuple_weight(self, tid, deduction):
        """Deduct tuple residual mass and synchronize every EC containing it."""
        if deduction <= CC_LP_EPS:
            return 0.0

        t_obj = self.tuples[tid]
        old_weight = t_obj['weight']
        if old_weight <= CC_LP_EPS:
            t_obj['weight'] = 0.0
            return 0.0

        new_weight = max(0.0, old_weight - deduction)
        actual_delta = old_weight - new_weight
        if actual_delta <= CC_LP_EPS:
            return 0.0

        t_obj['weight'] = 0.0 if new_weight <= CC_LP_EPS else new_weight

        for ref_eid in t_obj['ec_refs']:
            ec = self.ecs[ref_eid]
            ec['weight'] = max(0.0, ec['weight'] - actual_delta)
            if ec['weight'] <= CC_LP_EPS:
                ec['weight'] = 0.0

        return actual_delta

    def _materialize_ec_deduction(self, eid, deduction_mass):
        """
        Apply an EC-level bulk deduction proportionally to the EC's tuples.

        The EC snapshot is materialized through _deduct_tuple_weight so all
        other FD/CC references of each touched tuple stay synchronized before
        the next CC is processed.
        """
        ec = self.ecs[eid]
        W = ec['weight']
        if W <= CC_LP_EPS or deduction_mass <= CC_LP_EPS:
            return 0.0

        deduction_mass = min(deduction_mass, W)
        ratio = deduction_mass / W

        tuple_deductions = []
        for tid in ec['tuple_ids']:
            tuple_weight = self.tuples[tid]['weight']
            if tuple_weight > CC_LP_EPS:
                tuple_deductions.append((tid, tuple_weight * ratio))

        actual_total = 0.0
        for tid, tuple_deduction in tuple_deductions:
            actual_total += self._deduct_tuple_weight(tid, tuple_deduction)

        return actual_total

    def _bulk_trim_one_cc(self, cc_id):
        """
        Water-fill one conflict clique: subtract the third-largest active EC
        mass from every active EC, leaving at most two active RHS classes.
        """
        cc = self.ccs[cc_id]
        active_ecs = [
            eid for eid in cc['ec_ids']
            if self.ecs[eid]['weight'] > CC_LP_EPS
        ]
        if len(active_ecs) <= 2:
            return

        active_ecs.sort(key=lambda eid: self.ecs[eid]['weight'], reverse=True)
        tau = self.ecs[active_ecs[2]]['weight']
        if tau <= CC_LP_EPS:
            return

        # Compute all EC-level deductions from the current CC snapshot first;
        # then materialize each EC before moving on to another CC.
        ec_deductions = {
            eid: min(self.ecs[eid]['weight'], tau)
            for eid in active_ecs
            if min(self.ecs[eid]['weight'], tau) > CC_LP_EPS
        }

        for eid, deduction_mass in ec_deductions.items():
            self._materialize_ec_deduction(eid, deduction_mass)

        active_count = self.get_active_ec_count(cc_id)
        if active_count > 2:
            raise RuntimeError(
                f"CC-LP bulk trim failed for CC {cc_id}: "
                f"active_ec_count={active_count}"
            )

    def intra_fd_bulk_trim(self):
        """
        Stage 1: eliminate single-FD-induced triads with bulk water-filling.

        Each CC (one FD plus one fixed LHS value) is processed at most once.
        Since tuple/EC residual weights only decrease, later CCs cannot make a
        previously processed CC regain a third active EC.
        """
        for cc_id in list(self.ccs.keys()):
            if self.get_active_ec_count(cc_id) >= 3:
                self._bulk_trim_one_cc(cc_id)

        for cc_id in self.ccs:
            active_count = self.get_active_ec_count(cc_id)
            if active_count > 2:
                raise RuntimeError(
                    f"CC-LP Stage 1 invariant violated: CC {cc_id} "
                    f"has {active_count} active ECs"
                )

def cc_lp_approx(t, delta, rc, seed=None):
    """
    主控函数: bulk trim、LP 建模、Sigma-Partition 划分与舍入逻辑
    """
    # 1. 执行 CC 内 bulk water-filling 清洗
    state = CCLPState(t, delta)
    state.intra_fd_bulk_trim()  # Stage 1: bulk water-filling trim
    
    # 2. 提取残余实例 I' (仅保留残余权重 > 0 的元组)
    residual_tids = [tid for tid, obj in state.tuples.items() if obj['weight'] > 1e-9]
    if not residual_tids:
        # 如果全部死光了（极端冲突），返回空表
        empty_t = t.get_empty_table()
        return {empty_t.color_distribution: empty_t}

    # 3. Algorithm 4: FindPartition (获取大小受限的 Sigma-Partition)
    partitions = [set(residual_tids)]
    for fd in delta.fds:
        new_partitions = []
        for K in partitions:
            if not K: continue
            K1, K2 = set(), set()
            lhs_to_rhs = {}
            for tid in K:
                row = t.df.iloc[tid]
                # 提取 LHS 和 RHS 的值
                lhs_val = tuple(row[col] for col in fd.lhs.cols)
                rhs_val = row[fd.rhs.col]
                
                # 贪心分组：如果加入 K1 不违背当前 fd，则放入 K1，否则放入 K2
                if lhs_val not in lhs_to_rhs:
                    lhs_to_rhs[lhs_val] = rhs_val
                    K1.add(tid)
                elif lhs_to_rhs[lhs_val] == rhs_val:
                    K1.add(tid)
                else:
                    K2.add(tid)
            if K1: new_partitions.append(K1)
            if K2: new_partitions.append(K2)
        partitions = new_partitions

    # 4. 构建 MINIMIZE 视角的 半整数规划 (MHIP) - 等价类降维版
    m = gb.Model()
    m.Params.LogToConsole = 1
    if seed is not None:
        m.Params.Seed = seed


    x = {}
    y = {} # 新增：等价类辅助变量

    # 4.1 定义元组变量 X
    for tid in residual_tids:
        # x_i 代表删除指示器
        x[tid] = m.addVar(lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name=f"x{tid}")

    # 4.2 定义等价类变量 Y，并构建 O(N) 降维约束
    for fd_id, fd in enumerate(delta.fds):
        fd_ccs = [cc_id for cc_id, cc in state.ccs.items() if cc['fd_id'] == fd_id]
        
        for cc_id in fd_ccs:
            cc = state.ccs[cc_id]
            # 找出该 CC 中还有存活元组的 EC
            active_ec_ids = []
            for eid in cc['ec_ids']:
                alive_tuples = [tid for tid in state.ecs[eid]['tuple_ids'] if tid in residual_tids]
                if alive_tuples:
                    active_ec_ids.append((eid, alive_tuples))
            
            # Bulk trim 保证每个 CC 最多保留两个 active EC。
            if len(active_ec_ids) > 2:
                raise RuntimeError(
                    f"CC-LP Stage 1 invariant violated before LP: CC {cc_id} "
                    f"has {len(active_ec_ids)} active ECs"
                )
            if len(active_ec_ids) == 2:
                eid_u, tuples_u = active_ec_ids[0]
                eid_v, tuples_v = active_ec_ids[1]
                
                # 为这两个 EC 注册 Y 变量 (如果还没注册的话)
                if eid_u not in y:
                    y[eid_u] = m.addVar(lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name=f"y{eid_u}")
                    # 层次连结约束 1: y_u <= x_i
                    for tid in tuples_u:
                        m.addConstr(y[eid_u] <= x[tid])
                        
                if eid_v not in y:
                    y[eid_v] = m.addVar(lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name=f"y{eid_v}")
                    # 层次连结约束 2: y_v <= x_j
                    for tid in tuples_v:
                        m.addConstr(y[eid_v] <= x[tid])
                
                # 核心降维团约束：替代原本 N*M 条的 x_i + x_j >= 1
                m.addConstr(y[eid_u] + y[eid_v] >= 1)

    # 目标函数：最小化被删除的权值 (使用元组的残余血量)
    obj_expr = gb.LinExpr()
    for tid in residual_tids:
        obj_expr += state.tuples[tid]['weight'] * x[tid]
    m.setObjective(obj_expr, GRB.MINIMIZE)

    print("Start Optimization (Equivalence Class Encoding)")
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}, Constraints: {m.NumConstrs}, NNZ: {m.NumNZs}")
    m.optimize()
    assert m.status == GRB.OPTIMAL

    # 5. Algorithm 1: 基于 Sigma-Partition 的舍入策略 (Rounding)
    x_vals = {tid: x[tid].X for tid in residual_tids}
    
    # 寻找包含最多 1/2 权重分数解的 Partition K*
    best_K = None
    max_half_weight = -1.0
    for K in partitions:
        # 只统计 x_i = 1/2 的元组权重
        current_weight = sum(state.tuples[tid]['weight'] for tid in K if 0.49 < x_vals[tid] < 0.51)
        if current_weight > max_half_weight:
            max_half_weight = current_weight
            best_K = K
            
    if best_K is None:
        best_K = set()

    # 实施舍入: 
    # x_i == 0 意味着绝对安全，保留该元组。
    # x_i == 0.5 且属于 K*，被舍入为 0，保留该元组。
    # 其他均被舍入为 1 (删除)。
    keep_idxs = []
    for tid in residual_tids:
        val = x_vals[tid]
        if val <= 0.01:
            keep_idxs.append(tid)
        elif 0.49 < val < 0.51 and tid in best_K:
            keep_idxs.append(tid)

    # 6. 生成子集修复结果
    t0 = Table(t.representative_column, t.df.iloc[keep_idxs].reset_index(drop=True), t.labels)
    
    # 返回要求的数据格式映射
    res_map = {t0.color_distribution: t0}
    return res_map