import networkx as nx
from cclp_stage1 import CCLPState

def build_residual_conflict_graph(state: CCLPState) -> nx.Graph:
    """
    基于残余权重大于 0 的 Tuple，构建跨 FD 的无向冲突图。
    利用 Stage 1 构建好的 EC 和 CC 结构，可以避免 O(N^2) 的全局遍历。
    """
    G = nx.Graph()
    
    # 1. 过滤存活的节点
    for tid, t_obj in state.tuples.items():
        if t_obj['weight'] > 1e-9:
            G.add_node(tid)
            
    # 2. 添加冲突边 (只要两个存活元组在任意 FD 下属于同一个 CC 但不同的 EC，即产生冲突)
    for cc_id, cc in state.ccs.items():
        # 仅考虑包含存活元组的 EC
        active_ecs = []
        for eid in cc['ec_ids']:
            # 注意：在 Stage 2，我们不再依赖 EC 的 cached_total_weight，
            # 而是严格检查其内部是否还有存活的 Tuple
            alive_tuples_in_ec = [tid for tid in state.ecs[eid]['tuple_ids'] if state.tuples[tid]['weight'] > 1e-9]
            if alive_tuples_in_ec:
                active_ecs.append(alive_tuples_in_ec)
                
        # 不同的活跃 EC 之间两两连边
        if len(active_ecs) >= 2:
            for i in range(len(active_ecs)):
                for j in range(i + 1, len(active_ecs)):
                    for u in active_ecs[i]:
                        for v in active_ecs[j]:
                            # networkx 会自动去重重复的边
                            G.add_edge(u, v)
    return G

def cross_fd_trim(state: CCLPState):
    """
    Stage 2: 微观图论扫尾。
    使用 Chiba-Nishizeki 算法思想快速寻找并消除所有的冲突三角形。
    """
    iteration = 0
    while True:
        iteration += 1
        # 1. 构建当前残余权重的冲突图
        G = build_residual_conflict_graph(state)
        
        if G.number_of_edges() == 0:
            break # 没有任何冲突边，绝对安全，退出
            
        # 2. 构建 DAG (基于节点度数，从小指向大)
        degrees = dict(G.degree())
        DAG = nx.DiGraph()
        DAG.add_nodes_from(G.nodes())
        
        for u, v in G.edges():
            if degrees[u] < degrees[v]:
                DAG.add_edge(u, v)
            elif degrees[u] > degrees[v]:
                DAG.add_edge(v, u)
            else:
                # 度数相同，用节点 ID 打破平局，严格防止环
                if u < v:
                    DAG.add_edge(u, v)
                else:
                    DAG.add_edge(v, u)
                    
        triangles_eliminated = 0
        
        # 3. 极速枚举三角形并扣血
        for u in DAG.nodes():
            if state.tuples[u]['weight'] <= 1e-9:
                continue
                
            out_neighbors_u = set(DAG.successors(u))
            for v in out_neighbors_u:
                if state.tuples[v]['weight'] <= 1e-9:
                    continue
                    
                out_neighbors_v = set(DAG.successors(v))
                for w in out_neighbors_v:
                    if state.tuples[w]['weight'] <= 1e-9:
                        continue
                        
                    # 检查 u 和 w 之间是否有边 (无向图中连通即可)
                    if G.has_edge(u, w):
                        # 找到三角形 {u, v, w}！进行微观扣血
                        w_u = state.tuples[u]['weight']
                        w_v = state.tuples[v]['weight']
                        w_w = state.tuples[w]['weight']
                        
                        w_min = min(w_u, w_v, w_w)
                        
                        if w_min > 1e-9:
                            state.tuples[u]['weight'] -= w_min
                            state.tuples[v]['weight'] -= w_min
                            state.tuples[w]['weight'] -= w_min
                            triangles_eliminated += 1
                            
        # 如果在本轮遍历中没有扣除任何三角形的血量，说明图已达到无三角形 (Triangle-free) 状态
        if triangles_eliminated == 0:
            break