# CC-LP (Conflict Clique LP) 算法全流程设计文档

## 核心设计理念 (Core Philosophy)
本算法旨在解决计算不一致数据库最优子集修复（Optimal Subset Repair, OPTSR）的 NP-hard 问题。
结合原版 TE-LP 算法的近似比优势与等价类（Equivalence Class, EC）的降维特性，我们设计了 **“宏观等价类消团 + 微观图论扫尾”** 的两阶段无三角形化（Triad Elimination）配合半整数规划舍入的全新算法架构。

---

## 核心数据结构：三层交叉引用 (Triple-Level Cross-Reference)
为了在串行处理函数依赖 (FD) 时实现 $O(1)$ 的状态同步，算法底层维护以下结构：
1. **Tuple 阵列 (真实血量载体):** 记录 `tuple_id`, `residual_weight`（唯一真实残余权重）, `ec_refs`（所属的所有 EC 列表）。
2. **等价类 (EC) 桶 (宏观视图):** 记录 `ec_id`, `fd_id`, `tuple_refs`（包含的 Tuple）, `cc_ref`（所属的冲突团）, `cached_total_weight`（缓存的总权重，由内部 Tuple 动态计算得出）。
3. **冲突团 (CC) 战场 (操作单元):** 记录 `cc_id`, `ec_refs`（包含的 EC）, `active_ec_count`（非零权重的 EC 数量，$\le 1$ 即代表冲突解除）。

---

## 算法全生命周期 (The Four Stages)

### Stage 0: 战前准备 (Initialization & Indexing)
**目标：** 构建全局索引与初始状态（仅需扫描 1 次数据库）。
1. **分配初始权重：** 遍历所有 Tuple，初始化权重 $w_i$。
2. **聚类建类：** 对于每一个 $FD_j \in \Sigma$，根据左手边属性 (LHS) 的相同值，将 Tuple 聚类成等价类 (EC)。
3. **构建冲突团：** 同一 LHS 下，右手边属性 (RHS) 不同的 EC 自动构成冲突团 (CC)。
4. **建立网线：** 初始化 Tuple $\leftrightarrow$ EC $\leftrightarrow$ CC 的双向指针，并计算所有 EC 的初始 `cached_total_weight`。

### Stage 1: 宏观清剿 (Phase 1: Intra-FD Trim)
**目标：** 逐个 FD 串行处理，利用等价类批量消除单一 FD 下的所有密集冲突三角形（耗时占比极低，降维效果极强）。
1. **遍历战场：** 拿出 $FD_k$，遍历其所有包含至少 2 个活跃 EC 的冲突团 (CC)。
2. **寻找最小代价：** 在 CC 内部，找到 `cached_total_weight` 最小的非零等价类，记其权重为 $W_{min}$。
3. **等比例降权与隐式同步：** - 对于该 CC 内的每一个 $EC_m$，计算衰减比例 $ratio = W_{min} / EC_m.cached\_total\_weight$。
   - 遍历 $EC_m$ 内部的每个 Tuple，精确扣除 $deduction = Tuple.residual\_weight 	imes ratio$。
   - **关键同步：** 顺着该 Tuple 的 `ec_refs` 指针，找到它在**其他未处理 FD** 中所属的 EC，将其 `cached_total_weight` 减去 $deduction$。
4. **结束判定：** $FD_k$ 处理完毕后，进入下一个 FD。此时后续 FD 看到的 EC 权重已是被削弱后的真实状态。

### Stage 2: 微观扫尾 (Phase 2: Cross-FD Trim)
**目标：** 在极度稀疏的残余图中，利用 Chiba-Nishizeki 算法极速揪出跨界 (Cross-FD) 的零星三角形并彻底消除。
1. **脱离宏观：** 彻底抛弃 EC 视角。提取所有残余血量 `residual_weight > 0` 的 Tuple，构建残余顶点集 $V'$。
2. **构建稀疏图：** 在 $V'$ 中，若元组间存在任意 FD 冲突，则连边构成残余图 $G'$。
3. **极速找三角：** - 将 $G'$ 根据节点度数重定向为有向无环图 (DAG)，保证任意节点出度 $\le \sqrt{2m}$。
   - 运行 Chiba-Nishizeki 算法，在 $O(m \sqrt{m})$ 复杂度内枚举出所有的三角形 $T = \{t_a, t_b, t_c\}$。
4. **微观直接扣血：** 找到这三者的最小残余权重 $w_{min}$，直接从三者的血量中扣除。不再需要更新任何 EC。
5. **结束判定：** 直到图中绝对没有任何三角形。

### Stage 3: 终局结算 (Phase 3: LP Solving & Rounding)
**目标：** 利用无三角形图的数学性质，通过 LP 求解与分区智能舍入，获得最终的修复结果。
1. **退化与半整数性：** 提取最终存活的 Tuple 及其冲突关系。由于无三角形，所有 CC 的大小最大为 2。原本的 $P_{clique}$ 约束 $\sum y_k \ge |C| - 1$ 自然退化为传统的 Edge 约束，天然保证了解的半整数性质 $\{0, 1/2, 1\}$。
2. **求解 LP：** 将目标函数与约束送入 LP-Solver 求解。
3. **$\Sigma$-Partition 舍入：** - 将图中值为 $1/2$ 的元组集合 $S_{1/2}$，根据 $\Sigma$ 个函数依赖，划分为至多 $2^{|\Sigma|}$ 个无冲突的分区。
   - 找到包含 $S_{1/2}$ 权重最大的那个分区 $K^*$，白嫖其代价（将 $K^*$ 内的 $1/2$ 变量舍入为 0，即保留）。
   - 其余 $1/2$ 的变量舍入为 1（删除）。
4. **输出结果：** 最终变量为 0 的 Tuple 集合即为近似最优的 Subset Repair。

---

## 理论保障 (Theoretical Guarantees)
- **局部降权界限 (Trim Bound):** 无论在 Stage 1 的宏观降权还是 Stage 2 的微观降权，每消除一个冲突团或三角形所付出的代价，严格不超过最优解在该局部代价的 1.5 倍。
- **全局吸收定理 (Absorption Theorem):** 因为无三角形图在 LP 舍入阶段的近似比 $r = 2 - rac{1}{2^{|\Sigma|-1}} \ge 1.5$（当 $|\Sigma| \ge 2$ 时）。前期的 1.5 倍近似比被后期的 $r$ 完全吸收。
- **最终结论:** 该算法不仅在运行效率上实现了对传统 $O(n^3)$ 搜索的降维打击，在数学上依然严格继承了当前最优的近似比：$(2 - rac{1}{2^{|\Sigma|-1}})$。
