# CC-LP Bulk Water-Filling Trim 实现说明

> 目标：在不枚举 tuple-level triad 的前提下，利用 EC/CC 结构批量消除 **single-FD-induced triad**，从而继承 TE-LP 的近似比  
> \[
> 2 - \frac{1}{2^{|\Sigma|-1}}
> \]
>
> 本文档面向 Codex / 工程实现，重点描述数据结构、算法流程、伪代码、正确性直觉和实现检查项。

---

## 1. 背景与核心结论

TE-LP 中需要消除的 triad 不是全局 conflict graph 上任意三角形，而是由**同一个 FD** 诱导的三元完全冲突。

对于一个 FD：

```text
phi: X -> Y
```

如果三个 tuple 具有相同的 `X` 投影，但具有三个不同的 `Y` 投影，并且三者残余权重都大于 0，则它们构成该 FD 下的 triad。

因此，要继承 TE-LP 的近似比，不需要删除所有全局 mixed-FD triangles。只需要保证：

```text
对于每个 FD phi: X -> Y，
对于每个固定的 X-value group，
trim 结束后最多只剩两个 active RHS 等价类。
```

在 EC/CC 视角下，这等价于：

```text
每个 CC 的 active EC 数量 <= 2
```

其中：

- EC = `(fd_id, lhs_key, rhs_key)`
- CC = `(fd_id, lhs_key)`
- 同一个 CC 内不同 RHS 的 EC 两两冲突。

---

## 2. 从逐个 triad 删除到 bulk trim

### 2.1 原始逐个 triad 删除

原始 TE-LP 的 `TrimInstance` 可以理解为：

```text
while exists single-FD triad (t_i, t_j, t_k):
    delta = min(w_i, w_j, w_k)
    w_i -= delta
    w_j -= delta
    w_k -= delta
    remove zero-weight tuples
```

如果在 EC/CC 层实现，一个含有 `q >= 3` 个 active EC 的 CC 内一定存在 single-FD triad。

朴素 EC-level 做法是：

```text
while active_ec_count(CC) >= 3:
    W_min = min EC total residual weight in CC
    every active EC in CC loses W_min total mass
```

每轮至少清空一个 EC，直到该 CC 最多剩两个 active EC。

---

### 2.2 Bulk water-filling trim

上述多轮过程可以进一步压缩。

给定一个 CC，其 active EC 总残余权重为：

```text
W_1, W_2, ..., W_q    where q >= 3
```

按从大到小排序：

```text
W_(1) >= W_(2) >= W_(3) >= ... >= W_(q)
```

令：

```text
tau = W_(3)
```

也就是第三大 active EC 的总残余权重。

然后对每个 active EC 执行：

```text
new_W_E = max(W_E - tau, 0)
```

等价地，每个 EC 的总扣除量为：

```text
D_E = min(W_E, tau)
```

因为 `tau` 是第三大权重，所以处理后最多只有原来最大的两个 EC 仍然有正残余权重。因此一次 bulk trim 后：

```text
active_ec_count(CC) <= 2
```

---

## 3. 重要性质：bulk trim 不是逐个随机 triad 删除的等价模拟

需要明确：

```text
bulk water-filling trim 不等价于某个具体的随机 triad 删除序列。
```

例如某个 CC 中四个 EC 的权重为：

```text
n, n, n, 1
```

逐个随机 triad 删除时，如果总是选择前三个 EC，最后可能得到：

```text
0, 0, 0, 1
```

但 bulk trim 中：

```text
tau = n
```

于是：

```text
n, n, n, 1  ->  0, 0, 0, 0
```

会把所有 EC 都清空。

这不是正确性反例。原因是 bulk trim 是一个更强的 **clique-level shaving** 操作，而不是逐个 triad 删除的路径压缩。

正确性来自局部近似界，而不是来自与随机 triad 序列的完全等价。

---

## 4. 局部近似界

考虑一个 CC 中某一层高度 `h`。在这一层上，假设有 `q_h >= 3` 个 EC 仍然活跃。

bulk trim 在该层删除：

```text
q_h 份质量
```

而任何一致修复在这个 CC 内最多保留一个 EC，因此至少要删除：

```text
q_h - 1 份质量
```

所以该层局部损失因子为：

```text
q_h / (q_h - 1) <= 3/2
```

当 `q_h = 3` 时取最大值 `3/2`；当 `q_h > 3` 时更好。

因此，对整个 bulk trim 操作积分/累加后，局部损失因子仍然不超过：

```text
3/2
```

后续 LP + Sigma-partition rounding 的 TE-LP 近似比为：

```text
r = 2 - 1 / 2^(|Sigma| - 1)
```

当 `|Sigma| >= 2` 时：

```text
3/2 <= r
```

因此 Stage 1 的 bulk trim 损失可以被后续 rounding factor 吸收，最终继承 TE-LP 的近似比。

特殊情况：

```text
|Sigma| = 1
```

时，问题可以按每个 CC 独立精确求解：每个 LHS group 保留总权重最大的 RHS bucket，其余删除。

---

## 5. 数据结构

### 5.1 Tuple

```python
class TupleObj:
    def __init__(self, tuple_id, orig_weight):
        self.tuple_id = tuple_id
        self.orig_weight = float(orig_weight)
        self.residual_weight = float(orig_weight)
        self.ec_refs = []      # list[int], one EC per FD
        self.active = True
```

说明：

- `orig_weight` 用于最终实验成本统计。
- `residual_weight` 用于 trim 和 LP。
- `ec_refs` 指向该 tuple 在各 FD 下所属的 EC。
- `active=False` 表示该 tuple 已经被 trim 到 0，不进入后续 LP。

---

### 5.2 EC

```python
class EC:
    def __init__(self, ec_id, fd_id, lhs_key, rhs_key, cc_ref):
        self.ec_id = ec_id
        self.fd_id = fd_id
        self.lhs_key = lhs_key
        self.rhs_key = rhs_key
        self.cc_ref = cc_ref
        self.tuple_refs = []             # list[int]
        self.cached_total_weight = 0.0
        self.active = True
```

说明：

```text
cached_total_weight = sum(residual_weight[t] for t in tuple_refs if tuple.active)
```

当 `cached_total_weight <= EPS` 时，EC 视为 inactive。

---

### 5.3 CC

```python
class CC:
    def __init__(self, cc_id, fd_id, lhs_key):
        self.cc_id = cc_id
        self.fd_id = fd_id
        self.lhs_key = lhs_key
        self.ec_refs = []                # list[int]
        self.active_ec_count = 0
```

说明：

```text
active_ec_count = number of active ECs in this CC
```

Stage 1 的目标是使每个 CC 满足：

```text
active_ec_count <= 2
```

---

## 6. 初始化

### 6.1 输入格式

```python
I: list[int]                         # tuple ids
tuples: dict[int, tuple_record]      # tuple_id -> record
orig_weight: dict[int, float]
Sigma: list[FD]
```

其中 FD 可表示为：

```python
class FD:
    def __init__(self, fd_id, lhs_attrs, rhs_attrs):
        self.fd_id = fd_id
        self.lhs_attrs = lhs_attrs
        self.rhs_attrs = rhs_attrs
```

---

### 6.2 project 函数

```python
def project(tuple_record, attrs):
    """
    Return a hashable projection of tuple_record on attrs.
    attrs can be column names or column indices.
    """
    return tuple(tuple_record[attr] for attr in attrs)
```

---

### 6.3 initialize

```python
EPS = 1e-9

def initialize(I, tuples, orig_weight, Sigma):
    tuple_objs = {}
    ec_map = {}
    cc_map = {}

    next_ec_id = 0
    next_cc_id = 0

    # Create tuple objects
    for tid in I:
        tuple_objs[tid] = TupleObj(
            tuple_id=tid,
            orig_weight=orig_weight[tid],
        )

    # Helper maps from semantic keys to ids
    ec_key_to_id = {}
    cc_key_to_id = {}

    for fd in Sigma:
        for tid in I:
            lhs_key = project(tuples[tid], fd.lhs_attrs)
            rhs_key = project(tuples[tid], fd.rhs_attrs)

            cc_key = (fd.fd_id, lhs_key)
            ec_key = (fd.fd_id, lhs_key, rhs_key)

            if cc_key not in cc_key_to_id:
                cc_id = next_cc_id
                next_cc_id += 1
                cc_key_to_id[cc_key] = cc_id
                cc_map[cc_id] = CC(cc_id=cc_id, fd_id=fd.fd_id, lhs_key=lhs_key)

            cc_id = cc_key_to_id[cc_key]

            if ec_key not in ec_key_to_id:
                ec_id = next_ec_id
                next_ec_id += 1
                ec_key_to_id[ec_key] = ec_id
                ec_map[ec_id] = EC(
                    ec_id=ec_id,
                    fd_id=fd.fd_id,
                    lhs_key=lhs_key,
                    rhs_key=rhs_key,
                    cc_ref=cc_id,
                )
                cc_map[cc_id].ec_refs.append(ec_id)

            ec_id = ec_key_to_id[ec_key]

            ec_map[ec_id].tuple_refs.append(tid)
            tuple_objs[tid].ec_refs.append(ec_id)

    # Initialize EC weights
    for ec in ec_map.values():
        ec.cached_total_weight = sum(
            tuple_objs[tid].residual_weight
            for tid in ec.tuple_refs
            if tuple_objs[tid].active
        )
        ec.active = ec.cached_total_weight > EPS

    # Initialize CC active EC counts
    for cc in cc_map.values():
        cc.active_ec_count = sum(
            1 for eid in cc.ec_refs
            if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
        )

    return tuple_objs, ec_map, cc_map
```

---

## 7. 核心操作：tuple 权重扣除与同步

一个 tuple 同时属于多个 FD 下的 EC。  
因此，只要某个 tuple 的 `residual_weight` 被扣除，就必须同步更新它所属的所有 EC，以及对应 CC 的 `active_ec_count`。

```python
def deduct_tuple_weight(tid, deduction, tuple_objs, ec_map, cc_map):
    """
    Deduct residual weight from one tuple and synchronize all ECs containing it.
    """
    t = tuple_objs[tid]

    if not t.active:
        return 0.0

    old_weight = t.residual_weight
    new_weight = max(0.0, old_weight - deduction)
    actual_delta = old_weight - new_weight

    if actual_delta <= EPS:
        return 0.0

    t.residual_weight = new_weight

    if t.residual_weight <= EPS:
        t.residual_weight = 0.0
        t.active = False

    # Synchronize all ECs that contain this tuple
    for eid in t.ec_refs:
        ec = ec_map[eid]
        old_active = ec.active

        ec.cached_total_weight -= actual_delta

        if ec.cached_total_weight <= EPS:
            ec.cached_total_weight = 0.0
            ec.active = False

        # If EC becomes inactive, update its CC
        if old_active and not ec.active:
            cc = cc_map[ec.cc_ref]
            cc.active_ec_count -= 1

    return actual_delta
```

---

## 8. 核心操作：将 EC-level 扣除结算到 tuple

bulk trim 先在 EC 层计算每个 EC 要扣多少总质量：

```text
D_E = min(W_E, tau)
```

然后需要把 `D_E` 分配到该 EC 内部的具体 tuple。

推荐使用**等比例缩放**：

```text
ratio = D_E / W_E
delta_t = residual_weight[t] * ratio
```

这样扣除后：

```text
sum(delta_t for t in EC) = D_E
```

并且剩余 EC 内部 tuple 的相对比例保持不变。

```python
def materialize_ec_deduction(eid, deduction_mass, tuple_objs, ec_map, cc_map):
    """
    Apply an EC-level deduction to its tuples proportionally.
    This function must call deduct_tuple_weight so that all other ECs are synchronized.
    """
    ec = ec_map[eid]
    W = ec.cached_total_weight

    if W <= EPS or deduction_mass <= EPS:
        return

    deduction_mass = min(deduction_mass, W)
    ratio = deduction_mass / W

    # Important: record tuple deltas before modifying weights.
    tuple_deltas = []

    for tid in ec.tuple_refs:
        t = tuple_objs[tid]
        if t.active and t.residual_weight > EPS:
            delta = t.residual_weight * ratio
            tuple_deltas.append((tid, delta))

    for tid, delta in tuple_deltas:
        deduct_tuple_weight(
            tid=tid,
            deduction=delta,
            tuple_objs=tuple_objs,
            ec_map=ec_map,
            cc_map=cc_map,
        )
```

---

## 9. Bulk trim 一个 CC

```python
def bulk_trim_one_cc(cc, tuple_objs, ec_map, cc_map):
    """
    Bulk water-filling trim for one CC.

    Goal:
      If active_ec_count(CC) >= 3, make it <= 2 in one operation.

    This removes all single-FD-induced triads inside this CC.
    It does NOT attempt to remove arbitrary global conflict-graph triangles.
    """
    active_eids = [
        eid for eid in cc.ec_refs
        if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
    ]

    if len(active_eids) <= 2:
        cc.active_ec_count = len(active_eids)
        return

    # Sort active ECs by total residual weight, descending.
    active_eids.sort(
        key=lambda eid: ec_map[eid].cached_total_weight,
        reverse=True,
    )

    # Third largest EC mass.
    tau = ec_map[active_eids[2]].cached_total_weight

    if tau <= EPS:
        cc.active_ec_count = sum(
            1 for eid in cc.ec_refs
            if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
        )
        return

    # Precompute EC-level deductions using the current snapshot.
    ec_deductions = {}

    for eid in active_eids:
        W = ec_map[eid].cached_total_weight
        D = min(W, tau)

        if D > EPS:
            ec_deductions[eid] = D

    # Materialize EC deductions to tuples and synchronize all affected EC/CC states.
    for eid, D in ec_deductions.items():
        materialize_ec_deduction(
            eid=eid,
            deduction_mass=D,
            tuple_objs=tuple_objs,
            ec_map=ec_map,
            cc_map=cc_map,
        )

    # Recompute current CC active count for numerical safety.
    cc.active_ec_count = sum(
        1 for eid in cc.ec_refs
        if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
    )

    # This should hold except for numerical errors.
    if cc.active_ec_count > 2:
        raise RuntimeError(
            f"Bulk trim failed for CC {cc.cc_id}: "
            f"active_ec_count={cc.active_ec_count}"
        )
```

---

## 10. Stage 1：所有 CC 的 bulk trim

由于扣除只会减少权重，不会增加权重，因此：

- 如果某个 CC 已经被处理成 `<=2`，后续其他 CC 的同步更新只会让它更少，不会重新变成 `>=3`。
- 如果某个 CC 初始就是 `<=2`，后续同步更新也不会让它变成 `>=3`。
- 因此每个 CC 最多需要主动 bulk trim 一次。

```python
def intra_fd_ec_bulk_trim(tuple_objs, ec_map, cc_map):
    """
    Stage 1 of CC-LP.

    For every CC, if it has at least 3 active ECs, apply bulk water-filling trim.
    After this stage, every CC has active_ec_count <= 2.
    """

    for cc in list(cc_map.values()):
        # Refresh active count in case previous CCs changed it.
        cc.active_ec_count = sum(
            1 for eid in cc.ec_refs
            if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
        )

        if cc.active_ec_count >= 3:
            bulk_trim_one_cc(
                cc=cc,
                tuple_objs=tuple_objs,
                ec_map=ec_map,
                cc_map=cc_map,
            )

    active_tuple_ids = {
        tid for tid, t in tuple_objs.items()
        if t.active and t.residual_weight > EPS
    }

    # Global invariant check
    for cc in cc_map.values():
        active_count = sum(
            1 for eid in cc.ec_refs
            if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
        )
        cc.active_ec_count = active_count

        if active_count > 2:
            raise RuntimeError(
                f"Stage 1 invariant violated: CC {cc.cc_id} has {active_count} active ECs"
            )

    return active_tuple_ids
```

---

## 11. 为什么不能长期 lazy

可以在单个 CC 内部 lazy：

```text
先只在 EC 层计算 tau 和 D_E，再一次性 materialize 到 tuple。
```

但是不能跨 CC 长期 lazy。

原因：同一个 tuple 同时属于多个 FD 下的 EC。  
如果处理某个 CC 时减少了 tuple `t` 的残余权重，但没有同步到 `t` 在其他 FD 下所属的 EC，那么后续处理其他 CC 时会看到错误的 EC 总权重和 active 状态。

正确策略是：

```text
一个 CC 内部可以 bulk/lazy；
一个 CC 结束后必须 materialize 到 tuple；
同时同步该 tuple 所属的所有 EC 和 CC。
```

---

## 12. Stage 1 后的结构性质

Stage 1 结束后，对任意 FD：

```text
phi: X -> Y
```

和任意固定的 `X` 投影值 `x`，最多只有两个 active `Y` 投影值。

也就是说：

```text
每个 CC 的 active EC 数量 <= 2
```

因此，不存在任何 single-FD-induced triad。

注意：

```text
这并不意味着全局 conflict graph 是 triangle-free。
```

mixed-FD triangle 仍然可能存在，但它不影响 TE-LP 的 `2^|Sigma|` partition 证明。

---

## 13. Sigma-partition 构造

Stage 1 后，每个 FD 对每个 LHS group 最多有两个 active RHS 类型。  
因此每处理一个 FD，任意当前 block 最多被拆成两个子 block。  
最终 partition 数最多为：

```text
2^|Sigma|
```

```python
def find_sigma_partition(active_tuple_ids, tuples, Sigma):
    """
    Construct a Sigma-partition with at most 2^|Sigma| blocks.
    Precondition:
      For every FD and every LHS group, at most two active RHS values exist.
    """
    P = [set(active_tuple_ids)]

    for fd in Sigma:
        new_P = []

        for block in P:
            block0 = set()
            block1 = set()

            lhs_to_rhs_order = {}

            for tid in block:
                lhs_key = project(tuples[tid], fd.lhs_attrs)
                rhs_key = project(tuples[tid], fd.rhs_attrs)

                if lhs_key not in lhs_to_rhs_order:
                    lhs_to_rhs_order[lhs_key] = []

                if rhs_key not in lhs_to_rhs_order[lhs_key]:
                    lhs_to_rhs_order[lhs_key].append(rhs_key)

                if len(lhs_to_rhs_order[lhs_key]) > 2:
                    raise RuntimeError(
                        "Stage 1 invariant violated during partition: "
                        "more than two RHS values in one LHS group"
                    )

                if lhs_to_rhs_order[lhs_key].index(rhs_key) == 0:
                    block0.add(tid)
                else:
                    block1.add(tid)

            if block0:
                new_P.append(block0)
            if block1:
                new_P.append(block1)

        P = new_P

    return P
```

---

## 14. LP 模型：EC/CC 压缩约束

Stage 1 后，每个 CC 最多两个 active EC。  
因此每个 active conflict clique 只需要一个 EC-level 二元约束。

变量：

```text
x_t in [0, 1]      # tuple t 是否删除
y_E in [0, 1]      # EC E 是否整体删除
```

目标函数使用 residual weight：

```text
minimize sum_{t active} residual_weight[t] * x_t
```

约束：

1. 对每个仍有两个 active EC 的 CC：

```text
y_E1 + y_E2 >= 1
```

2. 对每个 active EC `E` 中每个 active tuple `t`：

```text
y_E <= x_t
```

3. 变量范围：

```text
0 <= x_t <= 1
0 <= y_E <= 1
```

如果一个 CC 中只有 0 或 1 个 active EC，则不产生冲突约束。

该星型模型避免显式生成完全二分图的 tuple-pair 边约束。

---

## 15. LP 舍入

求解 LP 后得到 `x_t`。理论上该解可以按半整数处理：

```text
x_t in {0, 1/2, 1}
```

实际实现中需要容忍浮点误差。

```python
def classify_lp_value(x, eps=1e-6):
    if x <= eps:
        return 0
    if abs(x - 0.5) <= eps:
        return 0.5
    if x >= 1 - eps:
        return 1
    return min([0, 0.5, 1], key=lambda v: abs(x - v))
```

舍入规则：

1. `x_t = 0`：保留。
2. `x_t = 1`：删除。
3. `x_t = 1/2`：使用 Sigma-partition。

令：

```text
P = {K_1, ..., K_p}, p <= 2^|Sigma|
```

找到 half-weight 最大的 block：

```text
K* = argmax_K sum_{t in K, x_t = 1/2} residual_weight[t]
```

然后：

```text
x_t = 1/2 and t in K*      -> keep
x_t = 1/2 and t not in K*  -> delete
```

```python
def round_solution(active_tuple_ids, residual_weight, x_value, partition):
    scores = []

    for K in partition:
        score = sum(
            residual_weight[t]
            for t in K
            if classify_lp_value(x_value[t]) == 0.5
        )
        scores.append(score)

    best_idx = max(range(len(partition)), key=lambda i: scores[i])
    K_star = partition[best_idx]

    kept = set()
    deleted_active = set()

    for tid in active_tuple_ids:
        c = classify_lp_value(x_value[tid])

        if c == 0:
            kept.add(tid)
        elif c == 1:
            deleted_active.add(tid)
        else:
            if tid in K_star:
                kept.add(tid)
            else:
                deleted_active.add(tid)

    return kept, deleted_active
```

---

## 16. 完整主流程

```python
def CC_LP_Bulk_TE_Ratio(I, tuples, orig_weight, Sigma):
    # Stage 0: Build Tuple/EC/CC indexes
    tuple_objs, ec_map, cc_map = initialize(
        I=I,
        tuples=tuples,
        orig_weight=orig_weight,
        Sigma=Sigma,
    )

    # Stage 1: Bulk water-filling trim per CC
    active_tuple_ids = intra_fd_ec_bulk_trim(
        tuple_objs=tuple_objs,
        ec_map=ec_map,
        cc_map=cc_map,
    )

    # Stage 2.1: Construct Sigma-partition
    partition = find_sigma_partition(
        active_tuple_ids=active_tuple_ids,
        tuples=tuples,
        Sigma=Sigma,
    )

    # Stage 2.2: Build compressed LP
    lp_model = build_compressed_lp(
        active_tuple_ids=active_tuple_ids,
        tuple_objs=tuple_objs,
        ec_map=ec_map,
        cc_map=cc_map,
    )

    # Stage 2.3: Solve LP
    x_value = solve_lp(lp_model)

    # Stage 2.4: Round
    residual_weight = {
        tid: tuple_objs[tid].residual_weight
        for tid in active_tuple_ids
    }

    kept, deleted_active = round_solution(
        active_tuple_ids=active_tuple_ids,
        residual_weight=residual_weight,
        x_value=x_value,
        partition=partition,
    )

    repair = kept

    # Tuples trimmed to zero are implicitly deleted.
    deleted_total = set(I) - repair

    # Final experimental cost should be computed using original weights.
    final_cost = sum(orig_weight[tid] for tid in deleted_total)

    return repair, final_cost
```

---

## 17. 实现检查清单

### 17.1 Stage 1 后检查每个 CC

```python
for cc in cc_map.values():
    active_count = sum(
        1 for eid in cc.ec_refs
        if ec_map[eid].active and ec_map[eid].cached_total_weight > EPS
    )
    assert active_count <= 2
```

---

### 17.2 检查每个 FD/LHS group 最多两个 RHS

```python
def check_fd_lhs_rhs_invariant(active_tuple_ids, tuples, Sigma):
    for fd in Sigma:
        lhs_to_rhs = {}

        for tid in active_tuple_ids:
            lhs_key = project(tuples[tid], fd.lhs_attrs)
            rhs_key = project(tuples[tid], fd.rhs_attrs)

            lhs_to_rhs.setdefault(lhs_key, set()).add(rhs_key)

        for lhs_key, rhs_set in lhs_to_rhs.items():
            assert len(rhs_set) <= 2
```

---

### 17.3 检查 partition block 一致性

```python
for K in partition:
    assert is_consistent(K, Sigma)
```

---

### 17.4 检查最终 repair 一致性

```python
assert is_consistent(repair, Sigma)
```

---

## 18. 实验日志建议

建议记录以下字段：

```text
n_original
n_active_after_trim
num_removed_by_trim
num_EC_initial
num_CC_initial
num_active_EC_after_trim
num_active_CC_after_trim
max_active_ec_per_CC_after_trim
partition_size
lp_num_x_variables
lp_num_y_variables
lp_num_constraints
final_cost_original_weight
stage0_time
stage1_bulk_trim_time
partition_time
lp_build_time
lp_solve_time
rounding_time
total_time
```

也可以额外记录 bulk trim 的统计：

```text
num_cc_trimmed
num_ec_deactivated_by_trim
total_residual_mass_before_trim
total_residual_mass_after_trim
largest_cc_size_before_trim
largest_cc_size_after_trim
```

---

## 19. 常见坑

### 坑 1：把 EC 的 tuple 数当成权重

如果所有 tuple 权重都是 1，则 EC size 等于 EC 总权重。  
但如果支持 weighted OPTSR，必须使用：

```text
W_E = sum residual_weight[t] for t in E
```

不能使用：

```text
|E| = number of tuples in E
```

---

### 坑 2：跨 CC 长期 lazy

不能只在 EC 计数上操作，而不更新 tuple 权重。  
每处理完一个 CC，必须 materialize 到 tuple，并同步所有 EC/CC。

---

### 坑 3：对 active_ec_count == 2 的 CC 继续 trim

`active_ec_count == 2` 时仍然存在二元冲突，但已经不存在 single-FD triad。  
不应该在 Stage 1 继续删除，应该交给 LP。

---

### 坑 4：误以为最终全局 conflict graph triangle-free

Stage 1 只保证没有 single-FD-induced triad。  
全局 mixed-FD triangle 仍可能存在。  
这不影响 TE-LP 近似比继承。

---

### 坑 5：最终成本使用 residual weight

LP 和 rounding 使用 residual weight。  
实验报告最终删除成本时，建议使用 original weight：

```text
cost(J, I) = sum_{t in I \ J} orig_weight[t]
```

---

## 20. 一句话总结

这个版本的 CC-LP Stage 1 可以理解为：

```text
对每个 FD/LHS 对应的 CC，
按 EC 总残余权重做一次 water-filling：
令 tau 为第三大 EC 权重，
所有 active EC 扣除 min(W_E, tau)，
并立即结算到 tuple 与所有相关 EC/CC。
```

它不枚举 triad，不做全局 triangle sweep，但能保证每个 CC 最多剩两个 active EC，因此可以构造至多 `2^|Sigma|` 个一致分区，并继承 TE-LP 的近似比。
