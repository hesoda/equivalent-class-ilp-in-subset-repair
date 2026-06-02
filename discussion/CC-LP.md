这份讨论总结为你梳理了我们基于你的“等价类（Equivalent Class）”概念与 Miao 等人的 TE-LP 算法，共同推演出的 **CC-LP (Conflict Clique LP)** 近似算法框架。建议将以下 Markdown 内容保存为你的研究笔记或论文大纲的雏形。

---

# Research Notes: CC-LP (Conflict Clique LP) 算法框架与推演

## 1. 核心思想与理论基础 (Theoretical Foundation)

本研究旨在解决计算不一致数据库最优子集修复（Optimal Subset Repair, OPTSR）的 NP-hard 问题。不同于传统基于“元组-边”冲突（$O(n^2)$）的模型，我们提出了一种基于等价类（Equivalence Class, EC）**和**冲突团（Conflict Clique, CC）的降维结构抽象。

- **理论突破 ($P_{clique} \subsetneq P_{edge}$):** 传统的边约束为 $x_i + x_j \ge 1$。我们的团约束为 $\sum_{E_k \in C} y_k \ge |C| - 1$。
    
    数学上已证明，我们的团约束不仅涵盖了传统的边约束，更能严格切断（Cut-off）传统 LP 松弛中出现的无意义分数解（例如 3-Clique 中的 $(0.5, 0.5, 0.5)$，因为 $0.5 \times 3 = 1.5 < 2$ 严格违背团约束）。这为算法提供了更紧致的 LP 下界。
    

## 2. 核心算法流程设计 (Two-Phase CC-LP)

为了继承 Miao 等人 TE-LP 算法 $(2 - \frac{1}{2^{|\Sigma|}-1})$ 的最优近似比，同时大幅降低计算复杂度，我们将算法设计为“宏观-微观”两阶段消团结合 LP 舍入的流程：

- **Phase 1: 宏观等价类消团 (CC-Level Trim)**
    
    在数据扫描构建等价类时，直接对单 FD 下的冲突团（CC）进行批量操作。对于大小 $\ge 3$ 的 CC，找出其中总权重最小的等价类 $W_{min}$，并对团内所有等价类扣除相应的权重。此操作瞬间瓦解图中绝大多数密集冲突。
    
- **Phase 2: 微观跨界消团 (Tuple-Level Cross-Trim)**
    
    Phase 1 结束后，同 FD 内的三角形已被全歼。残余网络极度稀疏，此时再使用元组级别的搜索寻找跨 FD (Cross-FD) 的冲突三角形并消除。
    
- **Phase 3: LP 求解与 $\Sigma$-分区舍入**
    
    将无三角形的残余图送入更紧致的 $P_{clique}$ 半整数规划模型中求解，并利用 $\Sigma$-Partition 进行智能舍入。
    

## 3. 关键机制与落地修正 (Key Mechanisms)

在将理论转化为实际算法时，我们推演出了以下关键机制以保证算法的鲁棒性与理论近似比：

### A. 等比例降权 (Proportional Reweighting)

为了解决“等价类整体删除导致误杀代价过大”的问题，采用**等比例降权**策略。

当一个冲突团需要减去总权重 $W_{min}$ 时，团内等价类 $E_k$ 中的每一个元组 $t_i$ 的权重 $w_i$ 按如下公式衰减：

$$w_i' = w_i - W_{min} \cdot \left( \frac{w_i}{W_k} \right)$$

这保证了权重不会出现负数，且同一元组在不同 FD 等价类中的损耗能够完美映射，符合理论上的“有界损失”。

### B. 极端剪枝效应 (Extreme Trimming Effect)

当冲突团内的部分等价类权重相近时，一次扣除 $W_{min}$ 可能会导致多个等价类的残余权重同时归零。一旦团内具有非零权重的等价类数量 $\le 1$，该局部冲突即在物理层面上被彻底消除，这使得 Phase 1 的执行效率呈指数级上升。

## 4. 跨 FD 冲突优化的降维打击 (Optimizing Cross-FD Search)

为了避免在 Phase 2 寻找跨 FD 三角形时陷入 $O(n^3)$ 的暴力搜索，我们利用图论性质和等价类结构进行了三重优化：

1. **鸽巢原理的红利:** 如果系统中仅有 2 个 FD ($|\Sigma| \le 2$)，全局图中绝对不可能存在 Cross-FD Triad。此时完全不需要 Phase 2，直接进入 Phase 3。
    
2. **特洛伊木马策略 (EC-Internal Edge Shortcut):** 跨界三角形必然包含两条同 FD 边，这意味着它的底边节点必定属于**同一个等价类**。因此，只需遍历等价类**内部**的元组是否在其他 FD 上发生冲突，一旦发现，即可通过该等价类对其外部的冲突元组进行批量歼灭。
    
3. **2-Core 拓扑剪枝:** 在 Phase 1 之后，剔除残余网络中度数 $< 2$ 的悬挂节点，再使用基于稀疏图的 $O(m \sqrt{m})$ 算法进行最后的排查。
    

## 5. 顺序依赖性与近似比吸收定理 (Sequential Bias & Absorption Theorem)

- **痛点 (顺序偏颇):** 贪心消除三角形时，先处理的 FD 会消耗元组权重，导致后处理的 FD 面临“残血打满血”的不公（Sequential Bias）。
    
- **工程解法:** 可采用全局同步贪心（Global Synchronous Trim）、初始权重切割（Weight Partitioning）或多轮随机重排（Randomized Permutation）来抹平偏颇，提升实际运行精度（Empirical Accuracy）。
    
- **理论解法 (吸收定理):** 即使存在顺序偏颇，也不影响算法的最坏情况近似比。因为消除三角形付出的最坏局部近似比是 $1.5$。而无三角形图在 LP 舍入阶段的最坏近似比是 $r = 2 - \frac{1}{2^{|\Sigma|-1}}$。只要 $|\Sigma| \ge 2$，则 $r \ge 1.5$。在总代价的数学不等式推导中，$1.5$ 会被更大的 $r$ **完全吸收**：
    
    $$C(Alg) \le 1.5 \times OPT_{trim} + r \times OPT_{LP} \le r \times (OPT_{trim} + OPT_{LP})$$
    
    因此，基于等价类的贪心减权操作，在理论近似比的证明上是绝对安全的。