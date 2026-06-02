import pandas as pd
from table import Table
from functional_dependency import FD, LHS, RHS, FDSet
from cclp_stage1 import CCLPState
from cclp_stage2 import cross_fd_trim

def test_module_2():
    # 1. 构造脏数据: 制造一个跨界三角形 (Cross-FD Triad)
    # t0 和 t1 违反 FD1 (A->B)
    # t1 和 t2 违反 FD2 (C->D)
    # t0 和 t2 违反 FD3 (E->F)
    data = {
        'A': [1, 1, 2],
        'B': [1, 2, 1],
        'C': [1, 2, 2],
        'D': [1, 1, 2],
        'E': [1, 2, 1],
        'F': [1, 1, 2]
    }
    df = pd.DataFrame(data)
    t = Table(representative_column=None, df=df)
    
    # 2. 构建 3 个独立的 FD
    fd1 = FD(LHS(['A']), RHS('B'))
    fd2 = FD(LHS(['C']), RHS('D'))
    fd3 = FD(LHS(['E']), RHS('F'))
    delta = FDSet([fd1, fd2, fd3])
    
    # 3. 初始化并运行 Stage 1
    state = CCLPState(t, delta)
    print("--- 初始 Tuple 残余血量 ---")
    for tid, t_obj in state.tuples.items():
         print(f"Tuple {tid}: 残余血量 = {t_obj['weight']}")
         
    state.intra_fd_trim()
    print("\n--- 执行 Stage 1 宏观等价类消团后 ---")
    print("预期：无变化，因为单一 FD 视角下最大 CC 大小仅为 2")
    for tid, t_obj in state.tuples.items():
         print(f"Tuple {tid}: 残余血量 = {t_obj['weight']}")
         
    # 4. 运行 Stage 2
    print("\n--- 执行 Stage 2 微观图论扫尾后 ---")
    cross_fd_trim(state)
    
    # 5. 验证消除结果
    for tid, t_obj in state.tuples.items():
        print(f"Tuple {tid}: 最终残余血量 = {t_obj['weight']:.4f}")

if __name__ == "__main__":
    test_module_2()