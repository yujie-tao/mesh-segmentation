from typing import List
import heapq
from queue import Queue
import numpy as np
from numpy.linalg import norm
from tqdm import tqdm
import time
import functools


def timed(func):
    # 函数运行计时
    @functools.wraps(func)
    def timed_wrapper(*args, **kwargs):
        print(f"{func.__name__}", end=" ")
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        print(f"{end_time - start_time:.2f}s")
        return result

    return timed_wrapper


class NeighborInfo:
    def __init__(self, e_vids, fid, angle, ang_dis, geo_dis):
        self.vids = e_vids  # 邻边的两个顶点的id
        self.fid = fid  # 邻面的id
        self.angle = angle  # 与邻面的夹角
        self.ang_dis = ang_dis  # 与邻面的角距离
        self.geo_dis = geo_dis  # 与邻面的测地距离
        self.dis = 0  # 与邻面的距离度量


class Face:
    def __init__(self, vs, vids):  # vs: 三个顶点的位置，vid: 三个顶点的id
        self.vids = vids
        self.center = sum(vs) / 3  # 三个顶点的质心位置
        n = np.cross(vs[1] - vs[0], vs[2] - vs[0])  # 法向量
        norm_len = norm(n)
        self.norm = n if norm_len < 1e-12 else n / norm_len  # 单位法向量
        self.label = 0  # 分割标签
        self.nbrs: List[NeighborInfo] = []  # 所有邻面的信息


class Model:
    @staticmethod
    def read_ply(ply_path):
        vertices, faces, v_num, f_num = [], [], 0, 0
        with open(ply_path, "r") as f:
            lines = [line.strip() for line in f.readlines()]
        for i, line in enumerate(lines):
            if line.startswith("element vertex"):
                v_num = int(line.split(" ")[-1])
            if line.startswith("element face"):
                f_num = int(line.split(" ")[-1])
            if line == "endheader":
                break
        for line in lines[-(v_num + f_num) : -f_num]:
            x, y, z = line.split(" ")[:3]
            vertices.append([float(x), float(y), float(z)])
        for line in lines[-f_num:]:
            v1, v2, v3 = line.split(" ")[1:4]
            faces.append([int(v1), int(v2), int(v3)])
        return np.array(vertices), np.array(faces)

    def __init__(self, ply_path):
        self.vs, fs = Model.read_ply(ply_path)  # 所有顶点位置
        self.fs = [Face(self.vs[f], f) for f in fs]  # 所有面片

        # STEP 1:计算所有邻居的信息
        self.avg_ang_dis = 0
        self.compute_neighbor()
        # STEP 2:计算任意两个面片间的最短路径
        self.f_dis = np.full((len(self.fs), len(self.fs)), np.inf)
        self.compute_shortest()

        self.label_nums = 0  # 目前所有面片已分割出多少种类

    @staticmethod
    def compute_dis(f0: Face, f1: Face, e_vs):  # e_vs是邻边的两个顶点位置
        # 计算两个面片之间的角距离
        angle = np.arccos(np.dot(f0.norm, f1.norm))
        is_convex = np.dot(f0.norm, f1.center - f0.center) < 1e-12
        eta = 0.2 if is_convex else 1.0  # 根据是否是凸的决定eta
        ang_dis = eta * (1 - np.dot(f0.norm, f1.norm))
        # 计算两个面片之间的测地距离
        # 计算方法：如果将两个面片展平，测地距离就是两质心相连的直线段，构成一个三角形，夹角就是angle0+angle1，用余弦定理就能算出距离
        axis, d0, d1 = (
            e_vs[1] - e_vs[0],
            f0.center - e_vs[0],
            f1.center - e_vs[0],
        )  # 3个共起点的向量
        axis_len, d0_len, d1_len = norm(axis), norm(d0), norm(d1)
        angle0 = np.arccos(np.dot(d0, axis) / d0_len / axis_len)
        angle1 = np.arccos(np.dot(d1, axis) / d1_len / axis_len)
        geo_dis = (
            d0_len * d0_len
            + d1_len * d1_len
            - 2 * d0_len * d1_len * np.cos(angle0 + angle1)
        )

        return angle, ang_dis, geo_dis

    def compute_neighbor(self):  # 将所有面片的邻边信息计算出来
        class Edge:
            def __init__(self, ev, fid):
                self.vids = (
                    (ev[0], ev[1]) if ev[0] < ev[1] else (ev[1], ev[0])
                )  # 两个顶点的id，升序
                self.fid = fid  # 面片id

        es = []  # 所有棱边
        for i, vids in enumerate([f.vids for f in self.fs]):
            es.extend(
                [
                    Edge((vids[0], vids[1]), i),
                    Edge((vids[1], vids[2]), i),
                    Edge((vids[2], vids[0]), i),
                ]
            )
        # 为所有面片找到与之相邻的面片，并计算相邻面片的角距离ang、测地距离geo和总距离
        visited_es = {}
        for e in es:
            if e.vids not in visited_es:
                visited_es[e.vids] = e.fid
            else:  # 遇到第二次才进行计算
                f0, f1 = visited_es[e.vids], e.fid
                angle, ang_dis, geo_dis = Model.compute_dis(
                    self.fs[f0], self.fs[f1], self.vs[list(e.vids)]
                )
                self.fs[f0].nbrs.append(
                    NeighborInfo(e.vids, f1, angle, ang_dis, geo_dis)
                )
                self.fs[f1].nbrs.append(
                    NeighborInfo(e.vids, f0, angle, ang_dis, geo_dis)
                )
        count = sum([len(f.nbrs) for f in self.fs])
        self.avg_ang_dis = (
            sum([sum([n.ang_dis for n in f.nbrs]) for f in self.fs]) / count
        )
        avg_geo_dis = sum([sum([n.geo_dis for n in f.nbrs]) for f in self.fs]) / count
        delta = 0.8
        for f in self.fs:
            for n in f.nbrs:
                n.dis = (
                    1 - delta
                ) * n.ang_dis / self.avg_ang_dis + delta * n.geo_dis / avg_geo_dis

    @timed
    def compute_shortest(self):
        import multiprocessing
        import functools
        import dijkstra

        f_nbrs_id = [[n.fid for n in f.nbrs] for f in self.fs]
        f_nbrs_dis = [[n.dis for n in f.nbrs] for f in self.fs]
        assert all([len(x) == 3 for x in f_nbrs_id])  # 要求每个面片都有3个邻居
        f_nbrs_id, f_nbrs_dis = np.array(f_nbrs_id), np.array(f_nbrs_dis)

        num_proc = 6  # 最短路算法并行，并行进程数
        with multiprocessing.Pool(num_proc) as p:
            results = [
                res
                for res in p.imap(
                    functools.partial(dijkstra.dijkstra_c, f_nbrs_id, f_nbrs_dis),
                    np.array_split(list(range(len(self.fs))), num_proc),
                )
            ]
        self.f_dis = np.concatenate(results, axis=0)

    def compute_flow(self, f_types):
        # f_types是所有面片目前的类型：无关区域0 边界区域1，2 模糊区域3。
        # 对f_types不为0的这些面片求最大流，函数返回时，f_types的3都会变成1或2
        # 参考：
        # Ford-Fulkerson增广路算法-EK算法。无向图等价于就直接用两个有向边就行。
        # https://www.desgard.com/2020/03/03/max-flow-ford-fulkerson.html
        # https://oi-wiki.org/graph/flow/max-flow/

        # 初始化流图，用于计算最大流
        class FlowEdge:
            def __init__(self, fro, to, cap, flow):
                self.fro = fro
                self.to = to
                self.cap = cap
                self.flow = flow

        # es[x]，点x的所有邻边信息（起始点为x），最后两个是用于的源点和汇点
        es: List[List[FlowEdge]] = [[] for _ in range(len(self.fs) + 2)]
        for i, f in enumerate(self.fs):
            for n in f.nbrs:
                es[i].append(
                    FlowEdge(i, n.fid, 1 / (1 + n.ang_dis / self.avg_ang_dis), 0)
                )
        start, target = len(es) - 2, len(es) - 1
        f_types = np.array(list(f_types) + [4, 4])
        for i, f_type in enumerate(f_types):
            if f_type == 1:
                es[start].append(FlowEdge(start, i, float("inf"), 0))
            elif f_type == 2:
                es[i].append(FlowEdge(i, target, float("inf"), 0))
        for i in range(len(es)):
            if f_types[i]:
                for e in es[i]:
                    e.flow = 0

        sum_flow = 0  # 总最大流
        while True:
            # STEP1: 从源点一直BFS，碰到汇点就停
            p = [-1] * (len(self.fs) + 2)  # p[x], BFS中x的父结点
            a = [0.0] * (len(self.fs) + 2)  # a[x]: BFS中x的父结点给到的流量
            a[start] = float("inf")
            q, q_history = Queue(), []  # 用q_history存储历史
            q.put(start)
            while not q.empty():
                cur = q.get()
                for e in es[cur]:  # 遍历cur的所有边e，如果e没有被搜索到且还有残余流量，就流
                    if f_types[e.to] != 0 and not a[e.to] and e.cap > e.flow:
                        p[e.to] = cur  # 设置父边
                        a[e.to] = min(a[cur], e.cap - e.flow)  # 设置流量
                        q.put(e.to)  # 继续搜
                        q_history.append(e.to)
                if a[target]:
                    break
            flow_add = a[target]
            if not flow_add:  # 已经搜索不到了，结束，BFS涉及的区域，都是1
                for i in q_history:
                    f_types[i] = 1
                for i in range(len(self.fs)):
                    if f_types[i] == 3:
                        f_types[i] = 2
                break
            # STEP2: 反向传播流量
            cur = target
            while cur != start:
                for e in es[p[cur]]:
                    if e.to == cur:
                        e.flow += flow_add  # 增加路径的flow值
                for e in es[cur]:
                    if e.to == p[cur]:
                        e.flow -= flow_add  # 减小反向路径的flow值
                cur = p[cur]
            sum_flow += flow_add
        return f_types

    def write_ply(self, ply_path):
        with open(ply_path, "w") as f:
            f.write(
                f"ply\nformat ascii 1.0\n"
                f"element vertex {len(self.vs)}\nproperty float x\nproperty float y\nproperty float z\n"
                f"element face {len(self.fs)}\nproperty list uchar int vertex_indices\n"
                f"property uint8 red\nproperty uint8 green\nproperty uint8 blue\n"
                f"end_header\n"
            )
            for v in self.vs:
                f.write(f"{v[0]} {v[1]} {v[2]}\n")
            for face in self.fs:
                f.write(f"3 {face.vids[0]} {face.vids[1]} {face.vids[2]} ")
                label = face.label
                f.write(
                    f"{60 * (label % 4 + 1)} {80 * ((label + 1) % 3 + 1)} {50 * ((label + 2) % 5 + 1)}\n"
                )
        print(f"save to {ply_path}")


class Segment:
    def __init__(self, model, level, fids=None):
        # global
        self.model = model
        self.fids = fids if fids else list(range(len(model.fs)))  # 只考虑哪些面片
        self.level = level  # 层次化分解的深度
        # local
        self.fs = [model.fs[fid] for fid in self.fids]
        self.f_dis = model.f_dis[self.fids][:, self.fids]

        def average(arr):
            return np.sum(arr) / (len(arr) * (len(arr) - 1))

        # 计算一些所需的最大距离/平均距离
        local_max_dis_fids = np.unravel_index(
            self.f_dis.argmax(), self.f_dis.shape
        )  # 最远的一对面片
        self.global_max_dis = self.model.f_dis.max() - self.model.f_dis.min()
        # assert self.global_max_dis != np.inf  # 要求是连通图
        self.global_avg_dis, self.local_avg_dis = average(self.model.f_dis), average(
            self.f_dis
        )

        def k_way_reps():
            # 选到其他各点距离之和最小的点初始点
            reps, G = [np.argmin(np.sum(self.f_dis, axis=1))], []
            for i in range(20):  # 20个试验点，每次新加入一个种子使最近的种子最远
                rep, max_dis = 0, 0.0
                for j in range(len(self.f_dis)):
                    min_dis = np.min([self.f_dis[j][reps]])
                    if min_dis > max_dis:
                        max_dis = min_dis
                        rep = j
                reps.append(rep)
                G.append(max_dis)
            # num = (
            #     np.argmax([G[num] - G[num + 1] for num in range(len(G) - 2)]) + 2
            # )  # 最大化G[num]-G[num+1]
            num = 2
            # NOTE: 如果想进行二路分解，只需要直接在此处设置num=2
            return num, reps[:num]  # 种子数和代表点

        (
            self.num,
            self.reps,
        ) = (
            k_way_reps()
        )  # 注意: reps是local变量，即reps[i]的值作为self.f_dis的索引而不是self.model.f_dis
        # 用uniques记录不重复的reps的索引，有可能出现种子重复的情况，只考虑不重复的种子
        self.uniques = np.sort(np.unique(self.reps, return_index=True)[1])

        if self.num == 2:
            rep0, rep1 = sorted(local_max_dis_fids)
            self.reps[0], self.reps[1] = rep0, rep1

        # 计算同类相邻面片夹角的极差
        max_ang, min_ang = 0, np.pi
        for f in self.fs:
            for n in f.nbrs:
                if self.model.fs[n.fid].label == f.label:
                    min_ang, max_ang = min(n.angle, min_ang), max(n.angle, max_ang)
        self.ang_diff = max_ang - min_ang

    def seg(self):
        prob = np.zeros((self.num, len(self.f_dis)))
        OFFSET, FUZZY = (
            self.model.label_nums,
            self.model.label_nums + self.num,
        )  # OFFSET之前共有多少种类，FUZZY标志模糊区域

        def compute_prob():
            for fid in range(len(self.f_dis)):
                if fid in self.reps:
                    prob[self.reps.index(fid)][fid] = 1
                    continue
                sum_prob = sum(
                    [1 / self.f_dis[fid][self.reps[u]] for u in self.uniques]
                )  # 只考虑不重合的点
                prob[:, fid] = 1 / self.f_dis[fid][self.reps] / sum_prob  # 计算平均

        def assign():  # 给面片打标签
            eps = 0.04 if self.num <= 3 else 0.02  # 确定清晰区域的阈值, 这个参数需要调，对分割结果影响较大
            counts = np.zeros(self.num)  # 每个类别的数量
            prob[[i for i in range(self.num) if i not in self.uniques]] = 0
            for fid in range(len(self.f_dis)):
                if len(self.uniques) > 1:
                    label1, label2 = heapq.nlargest(
                        2, range(len(self.uniques)), prob[self.uniques, fid].take
                    )
                    prob1, prob2 = prob[label1][fid], prob[label2][fid]
                else:
                    label1, label2, prob1, prob2 = self.uniques[0], -1, 1.0, 0.0
                if prob1 - prob2 > eps:
                    self.fs[fid].label = OFFSET + label1
                    counts[label1] += 1
                else:
                    self.fs[fid].label = FUZZY + label1 * self.num + label2

        def recompute_reps():
            # STEP1: 用论文3.3节最后一段的改进方法来计算P(fi∈Sj)
            assign()  # 先粗分类一下
            # rep_dis[k][i]表示第k类种子到第i个面片的距离，用面片i到所有第k类面片的的平均距离来表示
            rep_dis = np.zeros((self.num, len(self.f_dis)))
            counts = np.zeros(self.num)  # 每个类别的数量
            for k_f in range(len(self.f_dis)):  # 计算总距离累加
                k = self.fs[k_f].label - OFFSET
                if k < self.num:
                    counts[k] += 1
                    # k_f是一个新发现的第k类的面片，每个面片i累加上k_f到i(也就是i到k_f)的距离。最终得到i到所有k类面片的距离累加
                    rep_dis[k] += self.f_dis[k_f]
            for k in range(self.num):
                rep_dis[k] = rep_dis[k] / counts[k] if counts[k] else np.inf  # 求平均距离
            prob[:] = (
                1 / (rep_dis + 1e-12) / np.sum(1 / (rep_dis + 1e-12), axis=0)
            )  # 计算概率P
            # STEP2: 用论文3.3节第2部分计算新的种子
            rep_cost = np.dot(prob, self.f_dis)  # rep_cost[k][i]表示第k个类用i做种子的开销
            reps = list(np.argmin(rep_cost, axis=1))
            return reps, rep_cost

        def assign_fuzzy():
            for i in self.uniques:  # 两片模糊区域间的面片两两分割
                for j in self.uniques:
                    if j <= i:
                        continue
                    f_types = np.zeros(len(self.model.fs))
                    # STEP1: 确定具体分割的面片，找到哪些是模糊区域 3， 哪些是边界区域1，2， 哪些是无关区域0
                    for fid, f in zip(self.fids, self.fs):
                        if (
                            f.label == FUZZY + i * self.num + j
                            or f.label == FUZZY + j * self.num + i
                        ):
                            f_types[fid] = 3
                            for n in f.nbrs:
                                nf = self.model.fs[n.fid]
                                if nf.label == OFFSET + i:
                                    f_types[n.fid] = 1
                                elif nf.label == OFFSET + j:
                                    f_types[n.fid] = 2
                    # STEP2: 计算分割
                    f_types = self.model.compute_flow(f_types)
                    # STEP3: 执行分割结果
                    for fid in self.fids:
                        if f_types[fid] == 1:
                            self.model.fs[fid].label = OFFSET + i
                        elif f_types[fid] == 2:
                            self.model.fs[fid].label = OFFSET + j

        for _ in tqdm(range(20), desc=f"{self.level} step"):
            # 论文3.3中的STEP1: 计算概率
            compute_prob()
            # 论文3.3中的STEP2: 重新计算reps
            new_reps, cost = recompute_reps()
            # STEP3: 判断是否更新
            new_cost = [cost[i][rep] for i, rep in enumerate(new_reps)]
            old_cost = [cost[i][rep] for i, rep in enumerate(self.reps)]
            changed = any(
                [
                    (c1 < c0 - 1e-12 and r1 != r0)
                    for r1, r0, c1, c0 in zip(new_reps, self.reps, new_cost, old_cost)
                ]
            )
            if changed:
                self.reps = new_reps
                self.uniques = np.sort(np.unique(self.reps, return_index=True)[1])
            else:
                break

        recompute_reps()
        assign()  # 清晰部分
        assign_fuzzy()  # 模糊部分
        self.model.label_nums += self.num

        reps_f_dis = self.f_dis[self.reps][:, self.reps]
        local_max_patch_dis = np.max(reps_f_dis)
        if (
            self.level > 0 or local_max_patch_dis / self.global_max_dis < 0.1
        ):  # 最多只递归一层，可调
            return

        # 递归
        segments = []
        for sid in range(self.num):
            if sid in self.uniques:
                # 先统一建好建所有segment，再统一seg，不然seg导致label被换了标记，取模运算会有问题
                fids = [
                    fid
                    for fid in self.fids
                    if self.model.fs[fid].label % self.num == sid
                ]
                segments.append(Segment(self.model, self.level + 1, fids))
        for segment in segments:
            if (
                segment.ang_diff > 0.3
                and segment.local_avg_dis / segment.global_avg_dis > 0.2
            ):
                segment.seg()


if __name__ == "__main__":
    for ply_name in ["knife", "scissors", "binoculars", "knob", "mug"]:
        ply = ply_name  # 'dino' 'horse'
        mesh_model = Model(f"data/{ply}.ply")
        Segment(mesh_model, 2).seg()
        mesh_model.write_ply(f"data/{ply}-output.ply")
