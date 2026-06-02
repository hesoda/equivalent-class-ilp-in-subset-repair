# TE-LP 与 et-TE-LP 实现流程整理

> 来源：Miao et al., 2020, *The Computation of Optimal Subset Repairs*。本文档面向编码实现，重点整理论文第 4 节中的 BL-LP、TE-LP、et-TE-LP。注意：论文中的 TE-LP 仍然是基于**元组冲突边约束**的 LP/MHIP；它不是你的 EC/CC 聚合模型。

---

## 0. 问题输入与输出

### 输入

- `I`: 数据库实例，即元组集合。每个 tuple 有：
  - `tid`: 元组 id
  - `values`: 属性值字典或数组
  - `orig_weight`: 原始删除代价 `w_i`
  - `residual_weight`: 当前剩余权重，初始化为 `orig_weight`
- `Sigma`: FD 集合。每个 FD `phi = X -> Y` 包含：
  - `lhs_attrs = X`
  - `rhs_attrs = Y`

### 输出

- 一个近似 optimal subset repair `J`，即需要保留的 tuple id 集合。
- 删除集合为 `I \ J`。
- 输出方案成本使用**原始权重**计算：

```text
cost(J, I) = sum(orig_weight[t] for t in I if t not in J)
```

---

## 1. 基础函数

### 1.1 FD 冲突判断

两个元组 `a, b` 在 FD `phi: X -> Y` 下冲突，当且仅当：

```text
a[X] == b[X] and a[Y] != b[Y]
```

实现：

```python
def conflict_under_fd(a, b, fd):
    return project(a, fd.lhs_attrs) == project(b, fd.lhs_attrs) \
       and project(a, fd.rhs_attrs) != project(b, fd.rhs_attrs)
```

全局冲突：

```python
def conflict(a, b, Sigma):
    return any(conflict_under_fd(a, b, fd) for fd in Sigma)
```

### 1.2 集合对单个 FD 是否一致

集合 `K` 对 FD `X -> Y` 一致，当任意相同 `X` 值只对应一个 `Y` 值。

```python
def is_consistent_wrt_fd(tuple_ids, fd):
    lhs_to_rhs = {}
    for tid in tuple_ids:
        x = project(tid, fd.lhs_attrs)
        y = project(tid, fd.rhs_attrs)
        if x in lhs_to_rhs and lhs_to_rhs[x] != y:
            return False
        lhs_to_rhs[x] = y
    return True
```

增量版本用于 `FindPartition`：

```python
def can_add_to_fd_consistent_set(state, tid, fd):
    x = project(tid, fd.lhs_attrs)
    y = project(tid, fd.rhs_attrs)
    return x not in state or state[x] == y
```

---

## 2. BL-LP：TE-LP 调用的基础 LP 子程序

TE-LP 的最后一步会调用 BL-LP，因此需要先实现 BL-LP。

### 2.1 LP/MHIP 建模

对每个 tuple `t_i` 建变量：

```text
x_i = 0  表示保留 t_i
x_i = 1  表示删除 t_i
```

MILP：

```text
minimize    sum_i w_i * x_i
subject to  x_i + x_j >= 1,  for every conflicting pair (i, j)
            x_i in {0, 1}
```

LP relaxation：

```text
minimize    sum_i residual_weight_i * x_i
subject to  x_i + x_j >= 1,  for every conflicting pair (i, j)
            0 <= x_i <= 1
```

论文称该 LP 的极点具有半整数性质，即极点解落在 `{0, 1/2, 1}`。

### 2.2 生成冲突边

作为 baseline，可以直接 `O(n^2 * |Sigma|)` 枚举：

```python
edges = []
for i in range(n):
    for j in range(i + 1, n):
        if active[i] and active[j] and conflict(tuples[i], tuples[j], Sigma):
            edges.append((i, j))
```

### 2.3 求解 LP

调用 LP solver，例如 Gurobi / CPLEX / scipy.optimize.linprog / PuLP + HiGHS。

约束为：

```text
x_i + x_j >= 1
```

若 solver 返回的值有浮点误差，用阈值规整：

```python
EPS = 1e-7
if x <= EPS: value = 0
elif abs(x - 0.5) <= 1e-6: value = 0.5
elif x >= 1 - EPS: value = 1
else:
    # 理论上极点解应是半整数；若出现非半整数，通常说明 solver 返回了非极点最优解。
    # 可要求 simplex/basic solution，或对目标加极小扰动重新求解。
```

### 2.4 Sigma-partition-based rounding

BL-LP 需要给定一个 `Sigma-partition P(I, Sigma)`，即把所有 tuple 分成若干个互不相交的 consistent subsets。

给定 LP 解 `x0` 与 partition `P = [K1, ..., Kp]`：

1. 所有 `x_i = 0` 的 tuple 保留。
2. 所有 `x_i = 1` 的 tuple 删除。
3. 对 `x_i = 1/2` 的 tuple：
   - 找到一个分区 `K*`，使其中半整数 tuple 的**总 LP 权重**最大：

```text
K* = argmax_K sum(residual_weight_i * x_i for i in K if x_i == 1/2)
```

由于 `x_i = 1/2`，也等价于最大化 `sum(residual_weight_i)`。

4. `K*` 内的 `1/2` tuple 保留；其他分区中的 `1/2` tuple 删除。

伪代码：

```python
def BL_LP(active_tuple_ids, Sigma, partition):
    edges = build_conflict_edges(active_tuple_ids, Sigma)
    x = solve_lp_min_vertex_cover(active_tuple_ids, edges, residual_weight)

    K_star = max(
        partition,
        key=lambda K: sum(residual_weight[i] * x[i]
                          for i in K
                          if is_half(x[i]))
    )

    J = set()
    for i in active_tuple_ids:
        if is_zero(x[i]):
            J.add(i)
        elif is_half(x[i]) and i in K_star:
            J.add(i)
        # x_i == 1, or half but not in K_star: delete
    return J
```

---


## 3. TrimInstance：TE-LP 的三元冲突消除

### 3.1 triad 定义

论文中的 `triad` 是三个仍有正残余权重的 tuple：

```text
T = {t_i, t_j, t_k}
```

满足：

```text
residual_weight[t_i] > 0
residual_weight[t_j] > 0
residual_weight[t_k] > 0
```

并且存在某一个 FD `phi ∈ Sigma`，使得这三个 tuple 在 **同一个 FD `phi` 下两两冲突**：

```text
conflict_under_fd(t_i, t_j, phi)
conflict_under_fd(t_i, t_k, phi)
conflict_under_fd(t_j, t_k, phi)
```

也就是说，TE-LP 的 triad 不是任意全局 conflict graph 上的三角形。
如果三条冲突边分别由不同 FD 诱导，例如：

```text
conflict_under_fd(t_i, t_j, phi_1)
conflict_under_fd(t_i, t_k, phi_2)
conflict_under_fd(t_j, t_k, phi_3)
```

但不存在同一个 FD `phi` 同时诱导这三条边，那么它不是论文中 `TrimInstance` 要消除的 triad。

对于一个 FD：

```text
phi: X -> Y
```

三个 tuple 在该 FD 下构成 triad 等价于：

* 三个 tuple 的 `X` 投影相同；
* 三个 tuple 的 `Y` 投影两两不同；
* 三个 tuple 的 `residual_weight` 都大于 0。

换句话说，在某个 FD 的同一个 LHS group 内，只要存在至少 3 个仍有正权重的 RHS bucket，就可以从其中各取一个正权重 tuple 组成 triad。

---

### 3.2 conflict\_under\_fd

实现时需要先定义单 FD 下的冲突判断函数：

```python
def conflict_under_fd(t1, t2, fd):
    """
    Return True iff tuple t1 and tuple t2 conflict under one FD X -> Y.
    """
    return (
        project(t1, fd.lhs_attrs) == project(t2, fd.lhs_attrs)
        and project(t1, fd.rhs_attrs) != project(t2, fd.rhs_attrs)
    )
```

注意：

```python
def conflict(t1, t2, Sigma):
    return any(conflict_under_fd(t1, t2, fd) for fd in Sigma)
```

这个 `conflict` 是全局冲突图上的边判断，BL-LP 建 LP 约束时会用到它。

但 `TrimInstance` 中寻找 triad 时，不应该只检查：

```python
conflict(t_i, t_j, Sigma)
conflict(t_i, t_k, Sigma)
conflict(t_j, t_k, Sigma)
```

因为这样会把 mixed-FD triangle 也算进去。论文中的 TE-LP triad 要求三条边来自同一个 FD。

---

### 3.3 find\_triad：朴素实现

下面是忠实复现 TE-LP 的朴素版本。它逐个 FD 扫描，在每个 FD 内部寻找 single-FD-induced triad。

```python
from collections import defaultdict

EPS = 1e-9

def find_triad(active_tuple_ids, Sigma, tuples, residual_weight):
    """
    Find one triad in the sense of TE-LP.

    A returned triad (i, j, k) must satisfy:
      1. residual_weight[i], residual_weight[j], residual_weight[k] > EPS
      2. there exists one same FD phi: X -> Y such that
         i, j, k share the same X-value
         but have three pairwise different Y-values.

    This function does NOT search arbitrary triangles in the global
    union conflict graph.
    """
    for fd in Sigma:
        # Step 1: group active tuples by LHS value under this FD
        lhs_groups = defaultdict(list)

        for tid in active_tuple_ids:
            if residual_weight[tid] > EPS:
                lhs_key = project(tuples[tid], fd.lhs_attrs)
                lhs_groups[lhs_key].append(tid)

        # Step 2: inside each LHS group, bucket tuples by RHS value
        for lhs_key, tids in lhs_groups.items():
            rhs_buckets = defaultdict(list)

            for tid in tids:
                if residual_weight[tid] > EPS:
                    rhs_key = project(tuples[tid], fd.rhs_attrs)
                    rhs_buckets[rhs_key].append(tid)

            # Step 3: keep only RHS buckets containing at least one positive-weight tuple
            positive_rhs_keys = []

            for rhs_key, bucket in rhs_buckets.items():
                has_positive_tuple = any(
                    residual_weight[tid] > EPS for tid in bucket
                )
                if has_positive_tuple:
                    positive_rhs_keys.append(rhs_key)

            # Step 4: if at least three different RHS values exist,
            # pick one positive tuple from each of three RHS buckets
            if len(positive_rhs_keys) >= 3:
                triad = []

                for rhs_key in positive_rhs_keys[:3]:
                    bucket = rhs_buckets[rhs_key]
                    chosen_tid = next(
                        tid for tid in bucket
                        if residual_weight[tid] > EPS
                    )
                    triad.append(chosen_tid)

                return tuple(triad)

    return None
```

其中 `project` 可以实现为：

```python
def project(tuple_record, attrs):
    """
    Return the projection of tuple_record on attrs.
    attrs can be a list of attribute names or column indices.
    The return value must be hashable.
    """
    return tuple(tuple_record[attr] for attr in attrs)
```

---

### 3.4 重加权与删除

对找到的 triad：

```text
T = (i, j, k)
```

令：

```text
wT = min(residual_weight[i], residual_weight[j], residual_weight[k])
```

然后同时扣除三者的残余权重：

```text
residual_weight[i] -= wT
residual_weight[j] -= wT
residual_weight[k] -= wT
```

任何残余权重变成 0 的 tuple 都从 active instance 中移除。

完整伪代码如下：

```python
def TrimInstance(I, Sigma, tuples, orig_weight):
    """
    TE-LP TrimInstance.

    Input:
      I:
        iterable of tuple ids
      Sigma:
        list of FDs
      tuples:
        tuple_id -> tuple record
      orig_weight:
        tuple_id -> original weight

    Output:
      active:
        set of tuple ids whose residual weight remains positive
      residual_weight:
        tuple_id -> residual weight after trimming
      removed_by_trim:
        set of tuple ids whose residual weight becomes zero
    """
    active = set(I)
    removed_by_trim = set()

    residual_weight = {
        tid: float(orig_weight[tid])
        for tid in I
    }

    while True:
        T = find_triad(
            active_tuple_ids=active,
            Sigma=Sigma,
            tuples=tuples,
            residual_weight=residual_weight,
        )

        if T is None:
            break

        wT = min(residual_weight[tid] for tid in T)

        for tid in T:
            residual_weight[tid] -= wT

            if residual_weight[tid] <= EPS:
                residual_weight[tid] = 0.0

                if tid in active:
                    active.remove(tid)

                removed_by_trim.add(tid)

    return active, residual_weight, removed_by_trim
```

---

### 3.5 实现提示

* `TrimInstance` 使用并修改的是 `residual_weight`，不是 `orig_weight`。
* 被 trim 到 0 的 tuple 不进入后续 LP。
* 后续 `BL-LP(I', Sigma, P(I', Sigma))` 应该在 trim 后的 active instance `I'` 上运行。
* LP 的目标函数应使用 trim 后的 `residual_weight`。
* 最终实验报告 solution cost 时，通常需要用原始权重 `orig_weight` 计算删除成本。
* TE-LP 的 `TrimInstance` 只消除 single-FD-induced triad。
* 如果要搜索全局 conflict graph 上的任意 triangle，那是另一个更强的变体，不是论文原始 TE-LP。
* 为了忠实复现论文 baseline，建议先实现这里的朴素版本。
* 如果后续要加速，可以为每个 FD 动态维护：

```text
(fd_id, lhs_value) -> rhs_value -> active tuple ids
```

这样每次找 triad 时可以避免反复全表扫描。

---

## 4. FindPartition：TE-LP 的 `2^|Sigma|` 分区

TE-LP 在 `TrimInstance` 后得到无 triad 的实例 `I'`。论文证明此时存在大小至多 `2^|Sigma|` 的 `Sigma-partition`，并给出构造算法。

### 4.1 思路

从一个大集合 `K = I'` 开始。每处理一个 FD，就把当前每个分区至多拆成两个部分：

- `K0`: 贪心挑出的、对当前 FD 一致的集合；
- `K_remaining`: 未被挑入 `K0` 的剩余集合。

处理完 `sigma = |Sigma|` 个 FD 后，分区数量最多为 `2^sigma`。

### 4.2 实现伪代码

```python
def FindPartition(active_tuple_ids, Sigma):
    partitions = [set(active_tuple_ids)]

    for fd in Sigma:
        new_partitions = []

        for K in partitions:
            if not K:
                continue

            K0 = set()
            K_remain = set(K)
            state = {}  # lhs_value -> rhs_value for K0 under current fd

            # fixed deterministic order helps reproducibility
            for tid in list(K):
                x = project(tid, fd.lhs_attrs)
                y = project(tid, fd.rhs_attrs)
                if x not in state or state[x] == y:
                    K0.add(tid)
                    K_remain.remove(tid)
                    state[x] = y

            if K0:
                new_partitions.append(K0)
            if K_remain:
                new_partitions.append(K_remain)

        partitions = new_partitions

    return partitions
```

校验：

```python
assert len(partitions) <= 2 ** len(Sigma)
for K in partitions:
    assert is_consistent_wrt_all_fds(K, Sigma)
```

---

## 5. TE-LP 主流程

TE-LP 的整体结构：

```text
Input:  I, Sigma
Output: approximate S-repair J

1. I' = TrimInstance(I, Sigma)
2. P = FindPartition(I', Sigma)
3. J = BL_LP(I', Sigma, P)
4. return J
```

实现伪代码：

```python
def TE_LP(I, Sigma):
    # reset residual weights for this run
    for tid in I:
        residual_weight[tid] = orig_weight[tid]

    active = TrimInstance(I, Sigma)        # I'
    partition = FindPartition(active, Sigma)
    J_active = BL_LP(active, Sigma, partition)

    # final repair J contains only active tuples selected by BL-LP.
    # tuples removed by TrimInstance are treated as deleted.
    return J_active
```

成本评估：

```python
def repair_cost(J, I):
    return sum(orig_weight[t] for t in I if t not in J)
```

理论性质：

```text
Approximation ratio = 2 - 1 / 2^(|Sigma|-1)
Time complexity in paper = O(n^2), assuming |Sigma| is constant
```

---

## 6. et-TE-LP：基于 h-quasi-Turán cluster 的扩展

### 6.1 h-quasi-Turán cluster 定义

给定整数 `h > 1`。对某个 FD `phi: X -> Y`，一个集合 `K` 是 h-quasi-Turán cluster，当：

1. `K` 包含所有具有同一个 `X` 值的 tuple；
2. 满足：

```text
sum_{t in K} w_t >= (h + 1) * max_y sum_{t in K and t[Y] = y} w_t
```

也就是，该 LHS group 的总权重至少是最大 RHS bucket 权重的 `h+1` 倍。

直观理解：这个 LHS group 内部冲突非常分散，没有某个 RHS bucket 占主导；直接删除整个 group 的近似损失可以用 `h` 控制。

### 6.2 EliminateQuasiTuránClusters

论文没有给出该子过程的详细伪代码，只说明每轮对固定 `h` 先消除所有 disjoint h-quasi-Turán clusters，再运行 TE-LP。按定义可以实现如下。

候选 cluster 生成：

```python
def find_qt_candidates(I, Sigma, h, weight):
    candidates = []
    for fd in Sigma:
        lhs_groups = defaultdict(list)
        for tid in I:
            lhs_groups[project(tid, fd.lhs_attrs)].append(tid)

        for lhs_value, K in lhs_groups.items():
            total_w = sum(weight[t] for t in K)
            rhs_weight = defaultdict(float)
            for tid in K:
                rhs = project(tid, fd.rhs_attrs)
                rhs_weight[rhs] += weight[tid]
            max_bucket_w = max(rhs_weight.values()) if rhs_weight else 0.0

            if total_w >= (h + 1) * max_bucket_w:
                candidates.append({
                    "fd": fd,
                    "lhs_value": lhs_value,
                    "tuple_ids": set(K),
                    "total_weight": total_w,
                    "max_bucket_weight": max_bucket_w,
                })
    return candidates
```

选择 disjoint clusters：

```python
def select_disjoint_clusters(candidates):
    # 论文未规定选择顺序。为稳定实验，建议按 total_weight 降序。
    candidates = sorted(candidates, key=lambda c: c["total_weight"], reverse=True)
    selected = []
    used = set()
    for c in candidates:
        if c["tuple_ids"].isdisjoint(used):
            selected.append(c)
            used.update(c["tuple_ids"])
    return selected
```

消除：

```python
def EliminateQuasiTuranClusters(I, Sigma, h):
    # 使用 original weights 或当前传入实例的权重；作为 baseline 建议使用 orig_weight。
    candidates = find_qt_candidates(I, Sigma, h, orig_weight)
    selected = select_disjoint_clusters(candidates)
    eliminated = set().union(*(c["tuple_ids"] for c in selected)) if selected else set()
    I0 = set(I) - eliminated
    return I0, eliminated
```

注意：被 eliminated 的 cluster 中所有 tuple 都不进入 TE-LP；最终方案默认删除它们。

---

## 7. et-TE-LP 主流程

论文算法：

```text
J = empty
for h = 2, ..., n-1:
    I0 = EliminateQuasiTuránClusters(I, Sigma, h)
    J0 = TE-LP(I0, Sigma)
    if J0 is better than J:
        J = J0
return J
```

实现伪代码：

```python
def et_TE_LP(I, Sigma, h_values=None):
    if h_values is None:
        h_values = range(2, len(I))  # paper-faithful version: 2 <= h < n

    best_J = None
    best_cost = float("inf")

    for h in h_values:
        I0, eliminated = EliminateQuasiTuranClusters(I, Sigma, h)

        # TE_LP runs only on I0. It should reset residual weights for tuples in I0.
        J0 = TE_LP(I0, Sigma)

        # Since eliminated tuples are not in J0, they are treated as deleted.
        cost0 = repair_cost(J0, I)

        if cost0 < best_cost:
            best_cost = cost0
            best_J = set(J0)

    return best_J
```

工程优化：

```python
# For experiments, full h=2..n-1 is expensive.
# You can expose a parameter:
#   h_values = range(2, min(n, H_max + 1))
# or use only h values for which some FD-LHS group can satisfy the QT condition.
```

理论性质：

```text
TE-LP ratio:      2 - 1 / 2^(|Sigma|-1)
et-TE-LP ratio:   2 - 1 / 2^(|Sigma|-1) - epsilon
Paper time:       O(n^3), because it runs TE-LP for O(n) different h values
```

其中：

```text
epsilon = max_h { (1 - 1/h - 1/2^(|Sigma|-1)) * rho_h } >= 0
```

`rho_h` 表示第 `h` 轮中，被 quasi-Turán clusters 删除的权重占该轮最终删除成本的比例。

---

## 8. 实现时最容易踩坑的点

### 8.1 `x_i` 的语义

论文中：

```text
x_i = 0 表示保留
x_i = 1 表示删除
```

这和很多 maximum independent set / keep-variable 写法相反，代码中要统一。

### 8.2 LP 的权重使用 residual weight

`TrimInstance` 会降低部分 tuple 权重。后续 LP 应使用 `residual_weight`，但最终方案成本应使用 `orig_weight`。

### 8.3 K* 应按权重选，不建议按 tuple 数量选

为了匹配论文证明中的加权不等式，`K*` 应最大化半整数 tuple 的总权重：

```text
sum(residual_weight_i * x_i) for x_i = 1/2
```

如果只按数量选，在加权数据下可能不满足证明所需的 `1/p` 权重下界。

### 8.4 TE-LP 的 triad 是“同一个 FD 下”的三角

实现 `TrimInstance` 时，不要把由不同 FD 混合形成的三角也当作论文 triad。论文 triad 要求存在一个 FD `phi` 使三条边都由该 `phi` 诱导。

### 8.5 FindPartition 依赖无 triad 性质

`FindPartition` 的 `2^|Sigma|` 保证依赖于 `TrimInstance` 已经消除 triad。不要在原始 `I` 上直接调用它并期待分区一定 consistent。

### 8.6 et-TE-LP 的 cluster 选择顺序论文未细化

论文只说消除 disjoint h-quasi-Turán clusters，并说明可以通过对每个 FD 排序在 `O(n log n)` 时间完成。若实现时存在重叠候选 cluster，建议采用固定顺序，例如：

1. `total_weight` 降序；
2. FD id 升序；
3. LHS key 字典序。

这样实验可复现。

---

## 9. 推荐模块结构

```text
baseline_miao/
  data_model.py
    TupleRecord
    FunctionalDependency
    project(...)

  conflicts.py
    conflict_under_fd(...)
    conflict(...)
    build_conflict_edges(...)
    is_consistent_wrt_fd(...)
    is_consistent_wrt_all_fds(...)

  lp_solver.py
    solve_lp_min_vertex_cover(...)
    normalize_half_integral_solution(...)

  bl_lp.py
    BL_LP(...)
    greedy_sigma_partition(...)      # optional general BL-LP partition

  te_lp.py
    find_triad(...)
    TrimInstance(...)
    FindPartition(...)
    TE_LP(...)

  et_te_lp.py
    find_qt_candidates(...)
    select_disjoint_clusters(...)
    EliminateQuasiTuranClusters(...)
    et_TE_LP(...)

  metrics.py
    repair_cost(...)
    check_repair_consistency(...)
```

---

## 10. 最小实验输出

每个算法至少输出：

```text
algorithm_name
n
|Sigma|
num_conflict_edges
num_triads_trimmed              # TE-LP / et-TE-LP
num_qt_clusters_eliminated      # et-TE-LP
lp_num_vars
lp_num_constraints
runtime_total
runtime_trim
runtime_partition
runtime_lp
repair_cost_original_weight
is_consistent_output
```

对于 TE-LP，还建议记录：

```text
active_after_trim
removed_by_trim
residual_weight_sum_after_trim
partition_size
```

对于 et-TE-LP，还建议记录每个 h 的：

```text
h
num_selected_qt_clusters
num_eliminated_tuples
eliminated_original_weight
cost_after_TE_LP
```
