
**本章导语 (Introduction to Chapter 3)**:
简述本章的核心使命——打破传统元组级边约束（$P_{edge}$）在表达能力和理论界限上的局限性。引出本文提出的基于等价类的高维线性规划松弛模型（$P_{clique}$），并概述本章将从多面体几何的角度严格证明其具有更紧致的下界与投影等价性。

## 3.1 The Equivalent-Class ILP Formulation (基于等价类的整数线性规划模型)
*本小节目标：严格定义你的数学模型（变量、目标函数、约束）。*

* **决策变量定义 (Decision Variables)**:
    * 元组删除变量 $x_i \in \{0, 1\}$ (针对每个 tuple $t_i$)。
    * 等价类辅助删除变量 $y_k \in \{0, 1\}$ (针对每个 equivalence class $E_k$)。
* **目标函数 (Objective Function)**:
    * $\min \sum_{t_i \in D} w_i x_i$ (最小化删除元组的总权重)。
* **核心约束体系 (Constraint System)**:
    * **团约束 (Clique Constraints)**: $\sum_{E_k \in C} y_k \ge |C| - 1$。解释其物理意义：要打破一个完全冲突团 $C$，必须至少删除其中的 $|C|-1$ 个等价类。
    * **层级约束 (Hierarchical Constraints)**: $y_k \le x_i, \forall t_i \in E_k$。解释其物理意义：如果一个等价类被标记为删除（$y_k=1$），那么它包含的所有底层元组都必须被删除（$x_i=1$）。
* **松弛多面体定义 (The Polyhedron $P_{clique}$)**:
    * 将变量放宽至 $x_i \ge 0, y_k \ge 0$，形式化定义本章要研究的多面体 $P_{clique}$。

## 3.2 Tighter LP Relaxation Bound (更紧致的解空间下界证明)
*本小节目标：证明你的模型不仅能降维，而且在数学上比传统方法求出的分数解质量更高。*

* **定理声明 (Theorem 1)**: $P_{clique} \subseteq P_{edge}$。
    * **Bound Substitution 证明**: 从团约束出发，推导在任意两个属于不同等价类的冲突元组 $t_i, t_j$ 之间，能够通过代数放缩严格推导出 $x_i + x_j \ge 1$。证明 $P_{clique}$ 的解必然满足 $P_{edge}$ 的条件。
* **定理声明 (Theorem 2)**: $P_{clique} \subsetneq P_{edge}$ ($P_{clique}$ 严格包含于 $P_{edge}$)。
    * **Fractional Vertex Cut-off 证明**: 引入一个大小为 3 的冲突团（即三角形冲突）作为反例。
    * 展示在 $P_{edge}$ 中，$x_i = 0.5$ 是一个合法的（但质量很差的）无意义分数解。
    * 代入 $P_{clique}$ 的团约束，证明该分数解被严格切断（Cut-off），从而证明 $P_{clique}$ 切除了传统多面体中劣质的松弛空间，界限更紧致。

## 3.3 Projection Equivalence on Triangle-free Graphs (无三角形残余图下的投影等价性)
*本小节目标：连接理论与算法。证明当图中没有大团（$\ge 3$）时，辅助变量 $Y$ 可以被安全消去，且模型完美保留半整数性质。*

* **前提假设 (Assumption)**: 
    * 假设当前的冲突图中不存在大小 $|C| \ge 3$ 的冲突团（Triangle-free condition）。
* **傅里叶-莫茨金消元法投影证明 (FME Proof)**:
    * 针对 $|C| \le 2$ 的情况，写出此时的退化团约束（即 $y_u + y_v \ge 1$）。
    * 运用 FME 消元法，将 $y$ 的上界（受制于 $x$）和下界进行全配对组合。
    * 推导出消元后仅包含 $X$ 变量的不等式组完全等同于传统边约束 $x_i + x_j \ge 1$。
* **定理声明与半整数性质传递 (Theorem 3 & Half-integrality)**:
    * 得出结论：在无三角形假设下，$Proj_X(P_{clique}) = P_{edge}$。
    * 引用 Nemhauser & Trotter (1975) 的定理，指出既然此时投影等价，那么求解 $P_{clique}$ 自然继承了 $P_{edge}$ 经典的半整数性质（$x_i^* \in \{0, 1/2, 1\}$）。
* **为下一章铺垫 (Transition to Chapter 4)**:
    * 结语引出：“既然无三角形图具有如此优美的投影等价性和半整数性质，接下来的核心挑战就变成了：如何设计一种超大规模的极速算法，将初始稠密的冲突网络**无三角形化（Triad Elimination）**？”（完美过渡到第四章的 CC-LP 两阶段算法）。