# Research Context: Equivalent Class Subset Repair

## 1. Problem Definition & Core Concepts
- **Task:** Data cleaning via subset repair (deleting minimum tuples to satisfy constraints).
- **Target Constraint:** Functional Dependencies (FDs), e.g., $A \rightarrow B$.
- **Equivalence Class (EC):** A set of tuples that have strictly equal projections on the attributes involved in the FD (e.g., attributes $A$ and $B$).
- **Conflict Clique (CC):** Under the same left-hand side premise (e.g., identical projection on $A$), a set of Equivalence Classes that conflict with each other (differing on $B$). These ECs inherently form a complete graph (clique) of conflicts.

## 2. Mathematical Modeling (ILP Formulation)
Traditional methods map conflict graphs to Edge Constraints ($O(n^2)$ size). Our approach replaces this with **Clique Constraints** acting on Equivalence Classes.

### Variables
- $x_i \in \{0, 1\}$: Deletion indicator for tuple $t_i$ ($1$ means deleted).
- $y_k \in \{0, 1\}$: Deletion indicator for equivalence class $E_k$ ($1$ means the entire class is deleted).

### Objective Function
$$\min \sum x_i$$

### Constraints
1. **Clique Constraint (Conflict Resolution):**
   For each conflict clique $C$:
   $$\sum_{E_k \in C} y_k \ge |C| - 1$$
2. **Hierarchical Linkage Constraint:**
   For each tuple $t_i \in E_k$:
   $$y_k \le x_i$$

## 3. Theoretical Advantages & Formal Proof
Our Clique-based model ($P_{clique}$) provides a strictly tighter LP relaxation than the traditional Edge-based model ($P_{edge}$). 
**Theorem:** $P_{clique} \subsetneq P_{edge}$

### Part 1: Bound Substitution ($P_{clique} \subseteq P_{edge}$)
For any traditional edge constraint $x_i + x_j \ge 1$, tuples $t_i$ and $t_j$ belong to different equivalence classes $E_u, E_v$ within a conflict clique $C$. 
Starting from our clique constraint:
$$\sum_{E_k \in C} y_k \ge |C| - 1$$
We isolate $y_u$ and $y_v$:
$$y_u + y_v + \sum_{E_k \in C \setminus \{E_u, E_v\}} y_k \ge |C| - 1$$
Since $y_k \le 1$ in LP relaxation, the remaining sum is bounded by $|C| - 2$. Substituting this maximum possible value:
$$y_u + y_v + (|C| - 2) \ge |C| - 1 \implies y_u + y_v \ge 1$$
Given the hierarchical constraints $y_u \le x_i$ and $y_v \le x_j$, we directly obtain $x_i + x_j \ge 1$. Thus, any solution satisfying $P_{clique}$ also satisfies $P_{edge}$.

### Part 2: Fractional Vertex Cut-off ($P_{clique} \subsetneq P_{edge}$)
Consider a conflict clique $C$ composed of 3 equivalence classes $\{E_1, E_2, E_3\}$ (a triangle conflict).
In $P_{edge}$, the constraints are $y_1+y_2 \ge 1$, $y_2+y_3 \ge 1$, and $y_1+y_3 \ge 1$. A fractional optimal solution is $y_1 = y_2 = y_3 = 0.5$.
In $P_{clique}$, the constraint is $y_1 + y_2 + y_3 \ge 2$. 
The fractional solution $(0.5, 0.5, 0.5)$ yields a sum of $1.5$, which strictly violates our clique constraint ($1.5 < 2$). Therefore, $P_{clique}$ successfully cuts off fractional solutions present in $P_{edge}$, proving strict subset relationship and tighter bounds.