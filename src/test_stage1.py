import pandas as pd
from table import Table
from functional_dependency import FD, LHS, RHS, FDSet
from cclp_stage1 import CCLPState

def test_module_1():
    # 1. 构造脏数据:
    # A->B 是我们的约束。
    # 这里 A 都是 1，但 B 分别是 x (1个元组), y (2个元组), z (3个元组)
    # 这会形成 1个CC，内部包含 3个EC，权重分别为 1, 2, 3。这是一个典型的三角形密集冲突区。
    data = {
        'A': [1, 1, 1, 1, 1, 1],
        'B': ['x', 'y', 'y', 'z', 'z', 'z']
    }
    df = pd.DataFrame(data)
    
    # 构建 Table 对象 (不需要 representative_column)
    t = Table(representative_column=None, df=df)
    
    # 2. 构建 FDSet: A -> B
    fd = FD(LHS(['A']), RHS('B'))
    delta = FDSet([fd])
    
    # 3. 运行 Module 1
    print("--- 初始化 CC-LP 状态 ---")
    state = CCLPState(t, delta)
    
    # 验证 CC 和 EC 的构建
    assert len(state.ccs) == 1, "应该只有 1 个 CC (因为只有一个 LHS 值: 1)"
    cc_id = list(state.ccs.keys())[0]
    print(f"初始状态 CC_0 包含的 EC 数量: {len(state.ccs[cc_id]['ec_ids'])}")
    print(f"初始状态 CC_0 活跃 EC 数量: {state.get_active_ec_count(cc_id)}")
    for eid in state.ccs[cc_id]['ec_ids']:
        print(f"  EC_{eid} (B='{df.loc[state.ecs[eid]['tuple_ids'][0], 'B']}'): 权重 = {state.ecs[eid]['weight']}")
        
    print("\n--- 执行 Stage 1 宏观等价类消团 ---")
    state.intra_fd_trim()
    
    # 4. 验证消除结果
    print(f"执行后 CC_0 活跃 EC 数量 (预期 <= 2): {state.get_active_ec_count(cc_id)}")
    for eid in state.ccs[cc_id]['ec_ids']:
        print(f"  EC_{eid} 剩余权重 = {state.ecs[eid]['weight']:.4f}")
        
    print("\n--- 最终 Tuple 残余血量 ---")
    for tid, t_obj in state.tuples.items():
        print(f"Tuple {tid} (A={df.loc[tid,'A']}, B={df.loc[tid,'B']}): 残余血量 = {t_obj['weight']:.4f}")

if __name__ == "__main__":
    test_module_1()