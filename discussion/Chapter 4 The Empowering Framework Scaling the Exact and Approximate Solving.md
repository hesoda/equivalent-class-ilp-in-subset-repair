**本章导语 (Introduction to Chapter 4)**:
简述本章的核心目标。虽然第三章证明了 $P_{clique}$ 在理论上具有极大的优势，但如果仍然依靠传统的显式图（Explicit Graph）构建方式，依然无法摆脱预处理阶段的“内存墙”（Memory Wall）。本章将提出一套完整的可扩展计算框架，包含线性的无图化约束生成范式，以及针对近似求解的极速两阶段消团算法（CC-LP），从而在工程上彻底释放等价类模型的降维潜力。

## 4.1 Graph-Free Constraint Generation in $\mathcal{O}(N)$ Space (线性的无图化约束构造)
*本小节目标：阐述你是如何在不建图的情况下，直接把约束喂给通用 LP 求解器的。这是打破 OOM 瓶颈的最直接贡献。*

* **传统建图瓶颈 (The Bottleneck of Explicit Materialization)**:
    * 回顾 SOTA 精确求解器的工作流：必须在内存中实例化 $O(N^2)$ 的二维邻接表或边约束矩阵，导致极高的 Presolve 时间与物理内存溢出。
* **三层交叉引用数据结构 (Triple-Level Cross-Reference Index)**:
    * 引入你在内存中轻量级维护的数据结构：`Tuple` <-> `Equivalence Class (EC)` <-> `Conflict Clique (CC)`。指出该结构仅需扫描数据库一次即可建立。
* **无图化约束生成算法 (Graph-Free Generation Algorithm)**:
    * **层级约束生成**: 仅需遍历一遍 Tuple 数组，直接向求解器输出 $y_k \le x_i$，复杂度 $O(N)$。
    * **团约束生成**: 仅需遍历一遍 CC 数组，直接输出星型枢纽约束 $\sum y_k \ge |C|-1$，由于 $|CC| \ll N$，复杂度远低于 $O(N)$。
    * **结论**: 证明整个预处理阶段的空间复杂度和时间复杂度严格收敛于 $O(N)$，彻底消除了乘法级的约束爆炸。

## 4.2 Empowering Approximation: The CC-LP Algorithm (赋能近似求解：两阶段消团算法)
*本小节目标：呼应第 3.3 节的 FME 证明，展示如何用极其低廉的代价，将庞大密集的初始冲突图“无三角形化（Triad Elimination）”。*

* **算法设计动机 (Motivation)**:
    * 虽然原版 TE-LP 算法具有优秀的 $(2 - \frac{1}{2^{|\Sigma|-1}})$ 近似比，但其寻找和消除冲突三角形的过程需要 $O(N^3)$ 复杂度。我们提出 CC-LP 算法进行重构。
* **Stage 1: Macro Intra-FD Trim (宏观等价类消团)**:
    * **逻辑**: 针对单一 FD 内部的稠密冲突团（包含海量三角形）。
    * **操作**: 抛弃元组视角，直接在等价类（EC）层级寻找最小权重 $w_{min}$，对团内所有 EC 执行等比例降权。
    * **状态同步**: 通过更新底层 Tuple 的 `residual_weight`，实现多个 FD 之间 $O(1)$ 的状态同步。瞬间以宏观视角瓦解 $>90\%$ 的密集冲突。
* **Stage 2: Micro Cross-FD Trim (微观隐式图扫尾)**:
    * **隐式邻居生成器 (Implicit Neighbor Iterator)**: 针对残余的极度稀疏的跨 FD 散落三角形，提出**不构建残余图**的隐式遍历法。利用底层引用指针，在 $O(1)$ 内存开销下动态计算（而非存储）每个节点的活跃邻居。
    * **线性空间节点迭代法 (Node-Iterator Algorithm with $\mathcal{O}(N)$ Space)**: 结合全局一维标记数组（Mark Array），在极低的内存占用下快速排查出所有残留的三角形，并直接扣除权重。证明至此图中不再包含任何三角形。

## 4.3 LP Solving and Smart Rounding (终局求解与智能舍入)
*本小节目标：描述如何收尾，并将无三角形化的图送入求解器得到最终的 Repair 结果。*

* **连通分量切分 (Connected Component Decomposition)**:
    * 在将残余图送入 LP 求解器之前，对剩余的稀疏冲突网络进行连通分量（CCs）切分。
    * 解释其工程意义：防止求解器在内部 Presolve 阶段产生“填充效应（Fill-in）”导致内存二次爆炸，实现分治求解。
* **半整数解的获取与舍入 (Fractional Solving and Rounding)**:
    * 将约束集送入求解器。
    * 呼应 3.3 节的理论：指出此时返回的最优解必然是半整数的（$x_i^* \in \{0, 1/2, 1\}$）。
    * 采用经典的舍入策略（如按层级 FD 或阈值舍入），得到最终的 Consistent Subset，完成整个 Repair 流程。

## 4.4 Complexity Bounds Analysis (算法复杂度严格分析)
*本小节目标：给出严格的 Big-O 理论保证，为第五章的实验霸榜做理论背书。*

* **空间复杂度 (Space Complexity)**: 
    * 证明由于抛弃了 $O(N^2)$ 的边图构建，且隐式遍历仅需 $O(N)$ 标记数组，CC-LP 算法的峰值内存开销严格界定为 $\mathcal{O}(N + |\Sigma|)$。
* **时间复杂度 (Time Complexity)**: 
    * 分析 Stage 1 的 $O(N)$ 扫描耗时。
    * 分析 Stage 2 中 Node-Iterator 在极其稀疏图下的摊还时间复杂度界限。