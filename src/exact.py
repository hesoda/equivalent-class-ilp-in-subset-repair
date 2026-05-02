import gurobipy as gb
from gurobipy import GRB
from table import Table
from tqdm import tqdm

import pandas as pd
import time
import networkx as nx  # 引入图论库寻找极大团

def exact(t, delta, rc, method="GRB_ILP", seed=None):
    if method == "GRB_ILP":
        return exact_by_grb_ilp(t, delta, rc, seed)
    raise ValueError("Not Supported Optimizer")


# globalilp
# input: a Table t, a FDSet delta
# output: a mapping ColorDistribution -> (Sub-)Table (without conflicts)
def exact_by_grb_ilp(t, delta, rc, seed):
    map = {t.get_empty_table().color_distribution: t.get_empty_table()}

    m = gb.Model()
    # multi-threading
    m.setParam("Threads", 30)
    # add seed
    if seed is not None:
        m.Params.Seed = seed
    x = []

    for i in range(t.df.shape[0]):
        x.append(m.addVar(vtype=GRB.BINARY, name=f"r{i}"))

    # add constraints for FDs
    added = {}
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
                            if (ii, jj) not in added:
                                m.addConstr(x[ii] + x[jj] <= 1)
                                added[(ii, jj)] = 1

    # add constraints for RC
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
    for v in m.getVars():
        if v.VarName != "ans" and v.X != 0:
            idxs.append(int(v.VarName[1:]))
    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)
    map[t0.color_distribution] = t0
    return map

# relax-ilp-baseline
# input: a Table t, a FDSet delta
# output: (Sub-)Table (without conflicts) together with the LP relaxation objective value Z_LP and the x_i values for all tuples
def relax_lp_baseline(t, delta, seed=None):
    m = gb.Model()
    m.setParam("Threads", 30)
    m.Params.LogToConsole = 0
    # 【核心修改 1】关闭预处理
    m.setParam("Presolve", 0) 
    if seed is not None:
        m.Params.Seed = seed

    N = t.df.shape[0]
    # 【核心修改 2】变量改为连续型
    x = [m.addVar(vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name=f"r_{i}") for i in range(N)]

    added = {}
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
                            if (ii, jj) not in added:
                                m.addConstr(x[ii] + x[jj] >= 1)
                                added[(ii, jj)] = 1

    m.setObjective(gb.quicksum(x), GRB.MINIMIZE)
    print("Start LP Relaxation (Edge Baseline)")
    m.optimize()

    assert m.status == GRB.OPTIMAL

    # 【全新输出逻辑】：提取连续解
    x_vals = [v.X for v in x]
    df_out = t.df.copy()
    df_out['lp_x_val'] = x_vals
    
    t_out = Table(representative_column=t.representative_column, df=df_out, labels=t.labels)
    t_out.z_lp = m.ObjVal
    
    return t_out


# globalilp_equiv_class_rc
# input: a Table t, a FDSet delta, a RC Constraint rc, seed
# output: a mapping ColorDistribution -> (Sub-)Table (without conflicts & satisfying RC)
def exact_by_grb_ilp_equiv_class_rc(t, delta, rc, seed):
    # 初始化与 baseline 相同的返回字典结构
    map_res = {t.get_empty_table().color_distribution: t.get_empty_table()}

    m = gb.Model()
    m.setParam("Threads", 30)
    m.Params.LogToConsole = 1  # 跑通后可设为 0 关闭日志
    if seed is not None:
        m.Params.Seed = seed

    N = t.df.shape[0]
    
    # x 变量含义：1 表示被删除(Deleted)，0 表示被保留(Kept)
    x = m.addVars(N, vtype=GRB.BINARY, name="r")

    df_work = t.df.copy()
    df_work['_pos_idx'] = range(N)

    # ==========================================
    # 1. 添加 FD 等价类冲突约束 (维持线性稀疏度 O(N))
    # ==========================================
    for fd in delta.fds:
        lhs_grouped = df_work.groupby(fd.lhs.cols, dropna=False)
        
        for lhs_val, group_lhs in lhs_grouped:
            if group_lhs[fd.rhs.col].nunique(dropna=False) <= 1:
                continue
                
            rhs_grouped = group_lhs.groupby(fd.rhs.col, dropna=False)
            K = len(rhs_grouped)
            
            y = m.addVars(K, vtype=GRB.BINARY, name=f"y_{fd.lhs.cols}_{lhs_val}")
            m.addConstr(y.sum() <= 1)
            
            for k, (rhs_val, group_rhs) in enumerate(rhs_grouped):
                pos_idxs = group_rhs['_pos_idx'].values
                m.addConstrs((x[pos] + y[k] >= 1 for pos in pos_idxs), name="bind")

    # ==========================================
    # 2. 添加 RC 全局比例约束 (Distribution/Fairness Constraints)
    # ==========================================
    # total_kept 代表清洗后全表被保留的总行数
    total_kept = N - x.sum()
    
    for color in range(t.color_distribution.c):
        # 提取当前 color 类别人群在全表中的绝对索引
        color_pos_idxs = df_work[df_work[t.representative_column] == color]['_pos_idx'].values
        color_count = len(color_pos_idxs)
        
        # 统计当前类别人群被删掉的个数 (快速求和)
        color_x_sum = gb.quicksum(x[idx] for idx in color_pos_idxs)
        
        # 当前类别人群清洗后被保留的个数
        color_kept = color_count - color_x_sum
        
        # 获取该类别要求的最小比例
        rc_val = rc.constraint[t.labels[color]]
        
        # 添加约束：当前类的保留人数 >= 要求比例 * 总体保留人数
        m.addConstr(color_kept >= rc_val * total_kept, name=f"rc_{color}")

    # ==========================================
    # 3. 目标函数及求解
    # ==========================================
    # 我们的目标是最小化删除行数 (即最大化保留总行数)
    m.setObjective(x.sum(), GRB.MINIMIZE)

    print("Start Optimization (Equivalence Class Encoding with RC Fairness)")
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}, Constraints: {m.NumConstrs}, NNZ: {m.NumNZs}")
    
    m.optimize()
    assert m.status == GRB.OPTIMAL

    # 提取 x_i = 0 的行 (即被保留的行)
    idxs = [i for i in range(N) if x[i].X < 0.5]
    
    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)
    map_res[t0.color_distribution] = t0
    
    return map_res

# ilp-baseline with Yannakakis' Q^{oc}(G) Extended Formulation
# input: a Table t, a FDSet delta
# output: (Sub-)Table (without conflicts)
def exact_by_grb_ilp_with_yannakakis_ef(t, delta, seed):
    m = gb.Model()
    m.setParam("Threads", 30)
    
    # 【对抗性实验设置】必须关闭 Gurobi 的智能割平面，展示最原始的 LP 松弛
    m.Params.Cuts = 0
    m.Params.Heuristics = 0.0
    m.Params.Presolve = 0


    x = []
    if seed is not None:
        m.Params.Seed = seed

    # 1. 原始决策变量 (x=1 表示删除)
    for i in range(t.df.shape[0]):
        x.append(m.addVar(vtype=GRB.BINARY, name=f"r{i}"))

    # 2. 抽取冲突边和活跃节点
    edges = set()
    for fd in delta.fds:
        lhs_grouped = t.df.groupby(fd.lhs.cols)
        for _, lhs_idxs in lhs_grouped.groups.items():
            rhs_grouped = t.df.loc[lhs_idxs].groupby(fd.rhs.col)
            all_idxs = [rhs_idxs.tolist() for _, rhs_idxs in rhs_grouped.groups.items()]
            for i in range(len(all_idxs)):
                for j in range(i + 1, len(all_idxs)):
                    for ii in all_idxs[i]:
                        for jj in all_idxs[j]:
                            u, v = min(ii, jj), max(ii, jj)
                            edges.add((u, v))

    active_nodes = set()
    for u, v in edges:
        active_nodes.add(u)
        active_nodes.add(v)
        # 基础边约束 (Baseline 同款)
        m.addConstr(x[u] + x[v] >= 1, name=f"edge_{u}_{v}")

    # =========================================================
    # 【核心修改区：Yannakakis Q^{oc}(G) Extended Formulation】
    # 严格映射论文公式：o_{ij} (奇步数), e_{ij} (偶步数)
    # =========================================================
    o = {}
    e = {}
    
    # 声明高维辅助变量 O(V^2)
    for i in active_nodes:
        for j in active_nodes:
            # 根据论文：o_ij 和 e_ij 代表 walk lengths, 应当 >= 0
            o[i, j] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"o_{i}_{j}")
            e[i, j] = m.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name=f"e_{i}_{j}")

    # 约束 5: o_ii >= 1
    for i in active_nodes:
        m.addConstr(o[i, i] >= 1.0, name=f"odd_cycle_base_{i}")

    # 为了满足论文中 v_i v_k \in E 的无向边遍历，构造双向边集
    directed_edges = list(edges) + [(v, u) for (u, v) in edges]

    for (i, k) in directed_edges:
        # 约束 2: o_ik <= 1 - X_i - X_k (代入 X=1-x 后为 o_ik <= x_i + x_k - 1)
        m.addConstr(o[i, k] <= x[i] + x[k] - 1, name=f"o_bound_{i}_{k}")

        for j in active_nodes:
            # 约束 3: o_ij <= o_ik + e_kj
            m.addConstr(o[i, j] <= o[i, k] + e[k, j], name=f"walk_o_{i}_{k}_{j}")
            # 约束 4: e_ij <= o_ik + o_kj
            m.addConstr(e[i, j] <= o[i, k] + o[k, j], name=f"walk_e_{i}_{k}_{j}")
    # =========================================================

    m.setObjective(gb.quicksum(x[i] for i in range(len(x))), GRB.MINIMIZE)

    print("Start Optimization with Yannakakis EF")
    m.Params.LogToConsole = 1
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}, Constraints: {m.NumConstrs}, NNZ: {m.NumNZs}")
    m.optimize()

    if m.status == GRB.MEM_LIMIT:
        print("❌ 触发 OOM (Out of Memory)：超出 32GB 内存限制！")
        return None  
    elif m.status == GRB.TIME_LIMIT:
        print("❌ 触发 TLE (Time Limit Exceeded)：超出最大求解时间！")
        return None
    elif m.status != GRB.OPTIMAL:
        print(f"⚠️ 求解异常退出，状态码: {m.status}")
        return None

    # 由于是严紧多面体，放松到 x < 0.5 作为判定标准
    idxs = [i for i, v in enumerate(m.getVars()[:len(x)]) if v.X < 0.5]

    # 假定外层存在 Table 类
    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)

    return t0



# ilp-baseline
# input: a Table t, a FDSet delta
# output: (Sub-)Table (without conflicts)
def exact_by_grb_ilp_wo_rc(t, delta, seed):
    m = gb.Model()
    m.setParam("Threads", 30)
    
    # 【修改点 1：设置资源上限】
    # 限制 Gurobi 内部引擎最大使用 32GB 内存 (单位是 GB)
    m.Params.MemLimit = 32  
    # 强烈建议同时加上时间限制，例如 10 小时 (36000 秒)，防止它在 31GB 内存处卡死算几天几夜
    m.Params.TimeLimit = 36000 

    x = []
    if seed is not None:
        m.Params.Seed = seed

    for i in range(t.df.shape[0]):
        x.append(m.addVar(vtype=GRB.BINARY, name=f"r{i}"))

    added = {}
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
                            if (ii, jj) not in added:
                                m.addConstr(x[ii] + x[jj] >= 1)
                                added[(ii, jj)] = 1

    m.setObjective(gb.quicksum(x[i] for i in range(len(x))), GRB.MINIMIZE)

    print("Start Optimization")
    m.Params.LogToConsole = 1
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}, Constraints: {m.NumConstrs}, NNZ: {m.NumNZs}")
    m.optimize()

    # 【修改点 2：安全拦截 OOM 和 TLE 状态】
    # 检查是否因为触发了限制而退出
    if m.status == GRB.MEM_LIMIT:
        print("❌ 触发 OOM (Out of Memory)：超出 32GB 内存限制！")
        return None  # 返回 None 交给外层 driver.py 去记录日志
    elif m.status == GRB.TIME_LIMIT:
        print("❌ 触发 TLE (Time Limit Exceeded)：超出最大求解时间！")
        return None
    elif m.status != GRB.OPTIMAL:
        print(f"⚠️ 求解异常退出，状态码: {m.status}")
        return None

    # 只有在完美找到最优解时，才提取结果
    idxs = [i for i, v in enumerate(m.getVars()) if v.X == 0]

    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)

    return t0


# ilp-baseline
# input: a Table t, a FDSet delta
# output: (Sub-)Table (without conflicts)
def exact_by_grb_ilp_wo_rc_opt(t, delta, seed):
    m = gb.Model()
    m.setParam("Threads", 30)
    
    # 【修改点 1：对抗性实验核心设置】
    # 必须关闭 Gurobi 的自动割平面和启发式，剥去它的优化外衣，暴露最原始的 LP 松弛
    m.Params.Cuts = 0         # 关闭所有自动生成的割平面 (Clique, Zero-Half 等)
    m.Params.Heuristics = 0.0 # 关闭寻找可行解的启发式
    m.Params.Presolve = 0     # 关闭预处理 (让 Baseline 原形毕露的最佳参数)

    # 【修改点 1：设置资源上限】
    # 限制 Gurobi 内部引擎最大使用 32GB 内存 (单位是 GB)
    m.Params.MemLimit = 32  
    # 强烈建议同时加上时间限制，例如 10 小时 (36000 秒)，防止它在 31GB 内存处卡死算几天几夜
    m.Params.TimeLimit = 36000 

    x = []
    if seed is not None:
        m.Params.Seed = seed

    for i in range(t.df.shape[0]):
        x.append(m.addVar(vtype=GRB.BINARY, name=f"r{i}"))

    added = {}
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
                            if (ii, jj) not in added:
                                m.addConstr(x[ii] + x[jj] >= 1)
                                added[(ii, jj)] = 1

    m.setObjective(gb.quicksum(x[i] for i in range(len(x))), GRB.MINIMIZE)

    print("Start Optimization")
    m.Params.LogToConsole = 1
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}, Constraints: {m.NumConstrs}, NNZ: {m.NumNZs}")
    m.optimize()

    # 【修改点 2：安全拦截 OOM 和 TLE 状态】
    # 检查是否因为触发了限制而退出
    if m.status == GRB.MEM_LIMIT:
        print("❌ 触发 OOM (Out of Memory)：超出 32GB 内存限制！")
        return None  # 返回 None 交给外层 driver.py 去记录日志
    elif m.status == GRB.TIME_LIMIT:
        print("❌ 触发 TLE (Time Limit Exceeded)：超出最大求解时间！")
        return None
    elif m.status != GRB.OPTIMAL:
        print(f"⚠️ 求解异常退出，状态码: {m.status}")
        return None

    # 只有在完美找到最优解时，才提取结果
    idxs = [i for i, v in enumerate(m.getVars()) if v.X == 0]

    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)

    return t0

# 局部多面体强化模型 (Clique-Enhanced ILP)
# input: a Table t, a FDSet delta
# output: (Sub-)Table (without conflicts)
def exact_by_grb_ilp_clique_enhanced(t, delta, seed):
    m = gb.Model("Clique_Enhanced_Subset_Repair")
    m.setParam("Threads", 30)
    
    # 同样关闭 Gurobi 的自动外挂，以观察纯粹的数学模型威力
    m.Params.Cuts = 0        
    m.Params.Heuristics = 0.0 
    m.Params.Presolve = 0    

    m.Params.MemLimit = 32  
    m.Params.TimeLimit = 36000 

    x = []
    if seed is not None:
        m.Params.Seed = seed

    # 定义决策变量：x_i = 1 表示删除该元组
    for i in range(t.df.shape[0]):
        x.append(m.addVar(vtype=GRB.BINARY, name=f"r{i}"))

    # ==========================================
    # Step 1: 收集所有的冲突边，构建冲突图 G
    # ==========================================
    edges = set()
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
                            # 保证边是无向的，小索引在前，防止重复
                            u, v = min(ii, jj), max(ii, jj)
                            edges.add((u, v))

    # ==========================================
    # Step 2: 建立基础的边约束 (Edge Constraints)
    # ==========================================
    for u, v in edges:
        m.addConstr(x[u] + x[v] >= 1, name=f"edge_{u}_{v}")

    # ==========================================
    # Step 3: 寻找并注入极大团约束 (Maximal Clique Constraints)
    # ==========================================
    G = nx.Graph()
    G.add_nodes_from(range(t.df.shape[0]))
    G.add_edges_from(edges)
    
    # 使用 Bron-Kerbosch 算法找出图中的所有极大团
    cliques = list(nx.find_cliques(G))
    clique_count = 0
    
    for c in cliques:
        # 只有大小 >= 3 的团才需要额外的约束。
        # 因为大小为 2 的团就是一条普通的边，已经在 Step 2 被约束了。
        if len(c) >= 3:
            # 团约束公式：\sum x_i >= |C| - 1
            m.addConstr(gb.quicksum(x[i] for i in c) >= len(c) - 1, name=f"clique_{clique_count}")
            clique_count += 1

    # 目标函数：最小化被删除的元组数量
    m.setObjective(gb.quicksum(x[i] for i in range(len(x))), GRB.MINIMIZE)

    print("\nStart Optimization (Clique-Enhanced)")
    m.Params.LogToConsole = 1
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}")
    print(f"Base Edge Constraints: {len(edges)}")
    print(f"Maximal Clique Constraints injected: {clique_count}")
    print(f"--------------------------")
    
    m.optimize()

    # 安全拦截
    if m.status == GRB.MEM_LIMIT:
        print("❌ 触发 OOM (Out of Memory)：超出 32GB 内存限制！")
        return None 
    elif m.status == GRB.TIME_LIMIT:
        print("❌ 触发 TLE (Time Limit Exceeded)：超出最大求解时间！")
        return None
    elif m.status != GRB.OPTIMAL:
        print(f"⚠️ 求解异常退出，状态码: {m.status}")
        return None

    # 提取保留的元组 (x_i == 0)
    idxs = [i for i, v in enumerate(m.getVars()) if v.X == 0]
    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)

    return t0


def relax_lp_equiv_class(t, delta, seed=None):
    m = gb.Model()
    m.setParam("Threads", 30)
    m.Params.LogToConsole = 0
    m.setParam("Presolve", 0) 
    if seed is not None:
        m.Params.Seed = seed

    N = t.df.shape[0]
    x = [m.addVar(vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name=f"r_{i}") for i in range(N)]

    df_work = t.df.copy()
    df_work['_pos_idx'] = range(N)

    y_var_counter = 0

    for fd in delta.fds:
        lhs_grouped = df_work.groupby(fd.lhs.cols, dropna=False)
        for lhs_val, group_lhs in lhs_grouped:
            rhs_grouped = group_lhs.groupby(fd.rhs.col, dropna=False)
            if len(rhs_grouped) <= 1:
                continue
            
            y_vars = []
            for rhs_val, group_rhs in rhs_grouped:
                y = m.addVar(vtype=GRB.CONTINUOUS, lb=0.0, ub=1.0, name=f"y_{y_var_counter}")
                y_var_counter += 1
                y_vars.append(y)
                
                pos_idxs = group_rhs['_pos_idx'].tolist()
                for pos in pos_idxs:
                    m.addConstr(x[pos] + y >= 1)
                    
            m.addConstr(gb.quicksum(y_vars) <= 1)

    m.setObjective(gb.quicksum(x), GRB.MINIMIZE)
    print("Start LP Relaxation (Equivalence Class Encoding)")
    m.optimize()

    assert m.status == GRB.OPTIMAL

    # 【全新输出逻辑】：将所有的 x_i 提取出来拼接到 DataFrame 中
    x_vals = [v.X for v in x]
    df_out = t.df.copy()
    df_out['lp_x_val'] = x_vals  # 新增一列记录 LP 算出的删除概率 (保留为0，删除为1)
    
    # 构造新的 Table 对象，兼容原有输出
    t_out = Table(representative_column=t.representative_column, df=df_out, labels=t.labels)
    
    # 巧妙地将 Z_LP 作为属性挂载到对象上，方便外部直接读取
    t_out.z_lp = m.ObjVal 
    
    return t_out

def exact_by_grb_ilp_equiv_class(t, delta, seed):
    m = gb.Model()
    m.setParam("Threads", 30)
    m.Params.LogToConsole = 1
    if seed is not None:
        m.Params.Seed = seed

    N = t.df.shape[0]
    
    # 【核心加速 1】：使用 addVars 批量创建变量。
    # 这会直接在 C++ 底层分配内存，返回一个极速的 tupledict，彻底消除 Python 循环开销。
    x = m.addVars(N, vtype=GRB.BINARY, name="r")

    df_work = t.df.copy()
    df_work['_pos_idx'] = range(N)

    for fd in delta.fds:
        lhs_grouped = df_work.groupby(fd.lhs.cols, dropna=False)
        
        for lhs_val, group_lhs in lhs_grouped:
            # 【核心加速 2】：提前判定，避免不必要的 groupby 开销。
            # 如果这个 LHS 分组下 RHS 的唯一值只有一个，说明没有冲突，直接跳过！
            if group_lhs[fd.rhs.col].nunique(dropna=False) <= 1:
                continue
                
            rhs_grouped = group_lhs.groupby(fd.rhs.col, dropna=False)
            K = len(rhs_grouped)
            
            # 【核心加速 3】：批量创建当前冲突组的 y 变量。
            y = m.addVars(K, vtype=GRB.BINARY, name=f"y_{fd.lhs.cols}_{lhs_val}")
            
            # 【核心加速 4】：使用 tupledict.sum() 替代 gb.quicksum()。
            # x.sum() 和 y.sum() 是 Gurobi 为 tupledict 专门优化的 C 语言级别求和。
            m.addConstr(y.sum() <= 1)
            
            for k, (rhs_val, group_rhs) in enumerate(rhs_grouped):
                # 使用 .values 提取 numpy 数组，比 .tolist() 更快
                pos_idxs = group_rhs['_pos_idx'].values
                
                # 【核心加速 5】：使用 addConstrs 结合 Python 生成器。
                # 这会把整个约束生成的任务直接推送到 Gurobi 的 C++ 后端执行，速度提升极度夸张！
                m.addConstrs((x[pos] + y[k] >= 1 for pos in pos_idxs), name="bind")

    # 直接使用极速的 x.sum()
    m.setObjective(x.sum(), GRB.MINIMIZE)

    print("Start Optimization (Equivalence Class Encoding)")
    m.update()
    print(f"--- Gurobi Model Stats ---")
    print(f"Variables: {m.NumVars}, Constraints: {m.NumConstrs}, NNZ: {m.NumNZs}")
    m.optimize()

    assert m.status == GRB.OPTIMAL

    # 【修复点】：由于 x 现在是 tupledict {0: var0, 1: var1, ...}，
    # 我们应该直接遍历索引来提取值，v.X 依然适用。
    idxs = [i for i in range(N) if x[i].X < 0.5]
    
    t0 = Table(t.representative_column, t.df.iloc[idxs], t.labels)
    
    return t0

def partition_and_solve_ilp(t, delta, seed):
    """
    1. 按首个 FD LHS 分块 (Partition)
    2. 独立调用【等价类精确求解器】
    3. 合并结果 (Merge)
    4. 后处理：利用【簇基数权重】解决跨区哈希冲突
    """
    primary_fd = delta.fds[0] 
    partition_cols = primary_fd.lhs.cols
    
    grouped = t.df.groupby(partition_cols)
    repaired_dfs = []
    
    # 1 & 2. 分块独立求解
    for name, group_idxs in grouped.groups.items():
        sub_df = t.df.loc[group_idxs].copy()
        
        if len(sub_df) <= 1:
            repaired_dfs.append(sub_df)
            continue
            
        # 重置 index，确保传入 ILP 求解器时 index 是从 0 到 n-1 连续的
        sub_df = sub_df.reset_index(drop=True)
        sub_t = Table(t.representative_column, sub_df, t.labels)
        
        # 调用全新的等价类降维 ILP 求解器
        sub_t_repaired = exact_by_grb_ilp_equiv_class(sub_t, delta, seed)
        repaired_dfs.append(sub_t_repaired.df)
        
    # 3. Merge（合并所有子图的求解结果）
    merged_df = pd.concat(repaired_dfs).reset_index(drop=True)
    
    # 4. 后处理 (Post-processing)：跨分区哈希检测与【基数权重】仲裁
    final_df = merged_df.copy()
    for fd in delta.fds:
        lhs_grouped = final_df.groupby(fd.lhs.cols)
        valid_indices = []
        
        for _, lhs_idxs in lhs_grouped.groups.items():
            group_df = final_df.loc[lhs_idxs]
            
            # 检测哈希冲突
            rhs_counts = group_df[fd.rhs.col].value_counts()
            
            if len(rhs_counts) > 1:
                # 【你的思路落地】：利用同类数据的基数 (Cardinality) 作为权重
                # rhs_counts 本身就已经统计了每个局部等价类的 Tuple 数量 (即簇基数)
                # 我们选择基数最大的簇予以保留，将其余少数派作为噪音删除
                majority_rhs = rhs_counts.idxmax()
                keep_idxs = group_df[group_df[fd.rhs.col] == majority_rhs].index
                valid_indices.extend(keep_idxs)
            else:
                valid_indices.extend(group_df.index)
        
        # 逐层应用过滤，确保每处理完一个 FD，数据集都更加干净
        final_df = final_df.loc[valid_indices].reset_index(drop=True)
        
    return Table(t.representative_column, final_df, t.labels)