import pandas as pd
import numpy as np
from table import Table
from functional_dependency import FDSet

class CCLPState:
    def __init__(self, t: Table, delta: FDSet):
        self.t = t
        self.delta = delta
        
        # 三层交叉引用数据结构
        # 1. Tuple 阵列: 记录残余血量与所属的 EC 列表
        self.tuples = {i: {'weight': 1.0, 'ec_refs': []} for i in range(t.nrows())}
        
        # 2. EC 桶: 记录所属 fd_id, 包含的 tuple_ids, 所属的 cc_id, 以及动态缓存的总权重
        self.ecs = {} 
        
        # 3. CC 战场: 记录所属 fd_id, 包含的 ec_ids
        self.ccs = {} 
        
        self._build_indices()

    def _build_indices(self):
        """Stage 0: 战前准备，构建三层交叉引用"""
        ec_counter = 0
        cc_counter = 0
        df = self.t.df

        for fd_id, fd in enumerate(self.delta.fds):
            lhs_cols = fd.lhs.cols
            rhs_col = fd.rhs.col

            # 根据 LHS 聚类，形成冲突团 (CC)
            if len(lhs_cols) == 0:
                # 处理 Consensus FD (空 LHS)
                groups = {("dummy_lhs",): df.index.tolist()}
            else:
                grouped = df.groupby(lhs_cols)
                groups = grouped.groups

            for lhs_val, idxs in groups.items():
                cc_id = cc_counter
                cc_counter += 1
                self.ccs[cc_id] = {'fd_id': fd_id, 'ec_ids': []}

                # 在 CC 内部，根据 RHS 聚类，形成等价类 (EC)
                sub_df = df.loc[idxs]
                rhs_grouped = sub_df.groupby(rhs_col)

                for rhs_val, ec_idxs in rhs_grouped.groups.items():
                    ec_id = ec_counter
                    ec_counter += 1

                    tuple_ids = ec_idxs.tolist()
                    # 初始权重计算 (默认为 1.0，如果有 RC 约束可在此调整)
                    weight = len(tuple_ids) * 1.0 

                    self.ecs[ec_id] = {
                        'fd_id': fd_id,
                        'tuple_ids': tuple_ids,
                        'cc_id': cc_id,
                        'weight': weight
                    }
                    
                    self.ccs[cc_id]['ec_ids'].append(ec_id)

                    # 建立 Tuple 指向 EC 的网线
                    for tid in tuple_ids:
                        self.tuples[tid]['ec_refs'].append(ec_id)

    def get_active_ec_count(self, cc_id):
        """动态计算一个 CC 中权重 > 0 的 EC 数量"""
        return sum(1 for eid in self.ccs[cc_id]['ec_ids'] if self.ecs[eid]['weight'] > 1e-9)

    def intra_fd_trim(self):
        """Stage 1: 宏观等价类清剿"""
        for fd_id, fd in enumerate(self.delta.fds):
            # 获取属于当前 FD 的所有 CC
            fd_ccs = [cc_id for cc_id, cc in self.ccs.items() if cc['fd_id'] == fd_id]

            for cc_id in fd_ccs:
                # 当冲突团内的活跃等价类 >= 3 时，意味着存在密集的冲突三角形
                while self.get_active_ec_count(cc_id) >= 3:
                    cc = self.ccs[cc_id]
                    active_ecs = [eid for eid in cc['ec_ids'] if self.ecs[eid]['weight'] > 1e-9]
                    
                    # 找到总权重最小的等价类 W_min
                    min_ec_id = min(active_ecs, key=lambda eid: self.ecs[eid]['weight'])
                    w_min = self.ecs[min_ec_id]['weight']

                    # 对该 CC 内的所有活跃 EC 进行等比例降权
                    for eid in active_ecs:
                        ec = self.ecs[eid]
                        ratio = w_min / ec['weight']

                        # 深入到 Tuple 级别精确扣血，并隐式同步其他 FD 的状态
                        for tid in ec['tuple_ids']:
                            t_obj = self.tuples[tid]
                            deduction = t_obj['weight'] * ratio
                            
                            if deduction > 1e-9:
                                t_obj['weight'] -= deduction
                                # 【关键同步】：更新该 Tuple 所属的其他所有 EC 的缓存权重
                                for ref_eid in t_obj['ec_refs']:
                                    self.ecs[ref_eid]['weight'] -= deduction