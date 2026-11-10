"""多人的偏好聚合。

这是整个项目真正的技术点：把 N 个人对 M 个地点的打分矩阵，
压缩成一个「大家都还能接受」的排序。

为什么不能只用平均分：
    甲 10 分、乙 1 分、丙 9 分  → 平均 6.7，看起还行，但乙是去受罪的。
    甲 7 分、乙 6 分、丙 7 分  → 平均 6.7，没人特别难受。
两个方案平均分一样，体验天差地别。所以引入「最小满意度」做公平修正，
并用 Borda 计数和 minimax regret 两条独立路径做交叉验证。
"""

from __future__ import annotations

from dataclasses import dataclass

from .utility import borda_points

# 共识分的权重：整体满意度 vs 最不满意那个人的满意度。
MEAN_WEIGHT = 0.6
WORST_WEIGHT = 0.4


@dataclass
class Consensus:
    """一个地点在群体层面的聚合结果。"""

    poi_id: str
    mean: float
    worst: float
    worst_member: str
    consensus: float
    borda: float = 0.0
    regret: float = 0.0      # 0 最好（没人后悔），1 最差
    spread: float = 0.0      # 分数极差，越大代表分歧越大


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def consensus_for(poi_id: str, scores: dict[str, float]) -> Consensus:
    """对一个人数 >= 1 的群体，计算单个地点的共识指标。"""
    if not scores:
        raise ValueError("scores 不能为空")

    values = list(scores.values())
    mean = sum(values) / len(values)
    worst_member = min(scores, key=lambda k: scores[k])
    worst = scores[worst_member]
    spread = max(values) - min(values) if len(values) > 1 else 0.0

    return Consensus(
        poi_id=poi_id,
        mean=mean,
        worst=worst,
        worst_member=worst_member,
        consensus=_clip(MEAN_WEIGHT * mean + WORST_WEIGHT * worst),
        spread=spread,
    )


def borda_table(matrix: dict[str, dict[str, float]]) -> dict[str, float]:
    """Borda 计数：每人给所有地点排个名，第一名得 n-1 分，累加后归一到 0~1。

    它只看相对名次，不看绝对分数，所以能抵抗「某个人打分特别宽松」的干扰。
    """
    if not matrix:
        return {}
    poi_ids = list(next(iter(matrix.values())).keys())
    total: dict[str, float] = {pid: 0.0 for pid in poi_ids}
    for member_scores in matrix.values():
        ranking = sorted(poi_ids, key=lambda pid: member_scores[pid], reverse=True)
        for pid, pts in borda_points(ranking).items():
            total[pid] += pts
    peak = max(total.values()) or 1.0
    return {pid: v / peak for pid, v in total.items()}


def minimax_regret(matrix: dict[str, dict[str, float]]) -> dict[str, float]:
    """最小最大后悔值。

    每个人先说「我本来最高能拿多少分」，再看某个地点让他损失了多少。
    取所有人损失的最大值，就是选这个地点最坏情况下的后悔程度。
    返回 1 - 后悔，越大越好。
    """
    if not matrix:
        return {}
    poi_ids = list(next(iter(matrix.values())).keys())
    best_by_member = {m: max(s.values()) for m, s in matrix.items()}
    out: dict[str, float] = {}
    for pid in poi_ids:
        worst_regret = max(best_by_member[m] - s[pid] for m, s in matrix.items())
        out[pid] = _clip(1.0 - worst_regret)
    return out


def aggregate(matrix: dict[str, dict[str, float]]) -> list[Consensus]:
    """把打分矩阵聚合成按共识分降序排列的列表。"""
    if not matrix:
        return []
    poi_ids = list(next(iter(matrix.values())).keys())
    borda = borda_table(matrix)
    regret = minimax_regret(matrix)

    result = []
    for pid in poi_ids:
        item = consensus_for(pid, {m: s[pid] for m, s in matrix.items()})
        item.borda = borda.get(pid, 0.0)
        item.regret = regret.get(pid, 0.0)
        result.append(item)

    result.sort(key=lambda c: c.consensus, reverse=True)
    return result


def rank_agreement(matrix: dict[str, dict[str, float]]) -> float:
    """两种聚合规则的一致程度（Kendall tau，无并列版本）。

    用来在报告里说明「我们的结论不是调参调出来的」：
    Borda 排名和共识分排名越一致，结论越稳。
    """
    cons = aggregate(matrix)
    n = len(cons)
    if n < 2:
        return 1.0

    ids = [c.poi_id for c in cons]
    rank_borda = {c.poi_id: i for i, c in enumerate(sorted(cons, key=lambda c: c.borda, reverse=True))}
    rank_cons = {c.poi_id: i for i, c in enumerate(cons)}

    concordant = discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            a = rank_borda[ids[i]] - rank_borda[ids[j]]
            b = rank_cons[ids[i]] - rank_cons[ids[j]]
            if a * b > 0:
                concordant += 1
            elif a * b < 0:
                discordant += 1

    total = concordant + discordant
    return concordant / total if total else 1.0
