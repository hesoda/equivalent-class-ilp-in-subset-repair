
##一、 需要在实验代码中打点收集的数据 (Data Collection Checklist)

为了支撑完美的图表，你需要确保实验脚本能够稳定产出并记录以下字段（建议输出为 CSV 或 JSON 格式）：

### 1. 基础配置信息 (Base Info)

- `Dataset`：数据集名称
    
- `Scale`：数据规模（$N$ 的大小，如 10k, 50k, 100k, 1M）
    
- `Algorithm`：算法名称（`Ours`, `SOTA_Exact`, `VC_Approx`）
    

### 2. 核心性能指标 (Performance Metrics)

- `Status`：运行状态（`Optimal` / `TLE` (超时) / `OOM` (爆内存)）
    
- `Objective`：最终目标值（删除的脏数据行数）
    
- `Total_Time_s`：端到端总耗时（包含 Python 构图建模 + 求解时间）
    
- `Peak_RAM_MB`：操作系统层的真实峰值内存（**极度重要，体现防 OOM 能力**）
    
- `Optimality_Gap`：相对误差（仅针对近似算法计算，$\frac{|Obj_{approx} - Obj_{ours}|}{Obj_{ours}} \times 100\%$）
    

### 3. SOTA 与 Ours 的深度日志指标 (Gurobi Metrics)

_需要从 Gurobi Log 中解析提取：_

- `Initial_Rows`：进入求解器前的初始约束行数（**极其重要，解释 OOM 的元凶**）
    
- `Initial_Cols`：初始变量数
    
- `Initial_NNZ`：初始非零元素数
    
- `Presolve_Time_s`：预处理消耗时间
    
- `Root_LP_Objective`：根节点初始线性松弛解（可选，用于论证紧凑性）
    
- `Explored_Nodes`：探索的节点数（大概率都是 1）
    

### 4. 近似算法的专属指标 (Approx Metrics)

- `Graph_Build_Time_s`：显式构造冲突图消耗的时间
    
- `Graph_Edges`：冲突图中实际生成的边数
    

---

## 二、 论文图表规划方案 (Tables & Figures Planning)

### 1. 综合性能对比大表 (Master Performance Table)

- **形式：** 占据通栏宽度的大表格（`\begin{table*}`）。
    
- **横轴/行：** 不同的数据规模（如 10k, 50k, 100k, 1M）。
    
- **纵轴/列：** `Algorithm` | `Objective` | `Gap (%)` | `Total Time (s)` | `Peak RAM (MB)`。
    
- **作用：** 放在实验开篇，直接展示我们在 $5\times10^4$ 规模下打破了“精确与近似”的权衡（比 SOTA 快，比近似准且省内存），并展示我们在 $10^5$ 和 $10^6$ 规模下独活的统治力。
    

### 2. 初始约束爆炸曲线 (Constraint Growth Curve)

- **形式：** 折线图（X 轴为数据规模 $N$，Y 轴为 **初始约束数量 Initial_Rows**，**双对数坐标 Log-Log Scale**）。
    
- **展现效果：** SOTA 的曲线呈二次方陡峭上升，并在 $10^5$ 处中断（标记红色的 $\times$ OOM）；我们的曲线平缓贴地。
    
- **作用：** 从根本的数学结构上解释为什么 SOTA 会死于内存爆炸，直观证明等价类编码的优美性。
    

### 3. 精确求解时间拆解图 (Time Breakdown Stacked Bar)

- **形式：** 堆叠柱状图。X 轴为对比算法（针对 SOTA 没有挂掉的那个规模，如 50k），Y 轴为总耗时。柱子内部用不同颜色堆叠分为：`Presolve Time`（预处理）和 `Solving Time`（求解）。
    
- **展现效果：** SOTA 的柱子像摩天大楼，且 80% 以上的面积是 Presolve；我们的柱子极矮。
    
- **作用：** 暴击 SOTA 的建模质量，证明 SOTA 只是把寻找核心结构的算力压力全部甩给了 Gurobi，而我们的模型“原生纯净”。
    

### 4. 扩展性天花板 / 内存墙折线图 (Scalability: The Memory Wall)

- **形式：** 折线图（X 轴为数据规模 $N$，Y 轴为 **峰值内存 Peak RAM**，Y轴对数坐标）。图上画一条水平红色虚线代表服务器物理内存极限（如 32GB 或 64GB）。
    
- **展现效果：** SOTA 和 Approx 算法的曲线会快速上扬并“撞死”在红线上；我们的曲线保持极低水平贯穿全局。
    
- **作用：** 强调在现实大规模工业级数据下，本算法是唯一可行的方案。
    

### 5. 质量-资源双赢散点图 (Pareto Frontier Scatter Plot) _[备选/加分]_

- **形式：** 散点图。X 轴为 Peak RAM 或 Total Time（对数坐标），Y 轴为 Optimality Gap (%)。
    
- **展现效果：** 你的算法孤独而完美地占据在图表的**绝对左下角**（Gap=0, 时间极短, 内存极小），SOTA 在左上角，近似算法在右下角。
    
- **作用：** 直观展示本工作彻底打破了运筹学中“要准就慢，要快就差”的传统 Trade-off。
    

---

**记录提示：** 在跑后续实验时，千万不要觉得出现 `OOM` 或 `TLE` 是“坏数据”——在性能对比的叙事中，对手的崩溃正是你算法价值的最高赞美。一定要把 OOM 发生时的规模和崩溃的阶段（是构图阶段还是求解阶段）明确记录下来！