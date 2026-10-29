# -*- coding: utf-8 -*-
"""配色建议服务（应用的核心业务编排层）。

把「目标色 → 候选色号 → 配方求解 → 用量估算 → 替代色号」串成一条链，
输出供 UI 直接渲染的 ``PaintSuggestion`` 列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Tuple

from ..core.config import AppConfig
from ..core.color_models import normalize_rgb, rgb_to_lab, rgb_to_linear
from ..core.delta_e import DeltaEGrade, format_delta_e, grade_delta_e, resolve_delta_e
from ..data.paint_db import PaintDatabase, PaintEntry, get_database
from ..data.brands import BRANDS
from ..core.logging_setup import get_logger
from .alternatives import Alternative, find_alternatives
from .coverage import CoverageEstimate, CoverageInput, estimate_coverage, suggest_coats
from .provenance import ProvenanceSummary, provenance_of
from .recipe_engine import Recipe, build_direct_recipe, solve_recipe

logger = get_logger(__name__)

__all__ = ["PaintSuggestion", "PaintMatcher", "MATCH_POOL_SIZE"]

# 参与配方搜索的候选池大小（取目标色的最近 N 个可混色号）
MATCH_POOL_SIZE = 16

# 已经提醒过的未注册品牌键（避免每次 suggest 都刷同一条警告）
_warned_unknown_brands: set = set()


@dataclass
class PaintSuggestion:
    rank: int
    anchor: PaintEntry               # 主色号
    delta_e: float
    grade: DeltaEGrade
    recipe: Recipe
    coverage: CoverageEstimate
    alternatives: List[Alternative] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    tolerance: float = 3.0           # 本次计算使用的「直用容差」
    #: 这条结论的溯源总览（引用编号 / 置信度 / 来源缺口）。
    #: 在构建时算一次并缓存在这里 —— 渲染时重算会随卡片数量放大开销。
    provenance: ProvenanceSummary = field(default_factory=ProvenanceSummary)

    @property
    def is_direct(self) -> bool:
        """单一色号（不需要调配）。

        注意这**不等于**"可以直接用"：非首要建议在求解失败时会退回锚点单色，
        此时 ΔE 可能远大于容差（例如 ΔE 4.4 的单色近似）。能不能直接用要看
        :attr:`is_within_tolerance`。
        """
        return self.recipe.direct

    @property
    def is_within_tolerance(self) -> bool:
        return self.delta_e <= self.tolerance

    @property
    def mode_label(self) -> str:
        """给界面用的三种状态：直用 / 单色近似 / 需调配。"""
        if self.is_direct and self.is_within_tolerance:
            return "可直接瓶用"
        if self.is_direct:
            return "单色近似（色差偏大）"
        return "需调配"

    @property
    def title(self) -> str:
        if self.is_direct:
            return f"{self.anchor.full_label} {self.anchor.name}"
        return " + ".join(f"{c.paint.code}" for c in self.recipe.components)


class PaintMatcher:
    """配色建议计算器（无状态，可复用）。"""

    def __init__(self, db: Optional[PaintDatabase] = None) -> None:
        # 必须判 None 而不是判真假：PaintDatabase 实现了 __len__，空库是「假值」，
        # ``db or get_database()`` 会把调用方明确传入的空库悄悄换成全库——
        # 「空库应该返回空建议」的边界用例因此永远测不出来（拿到的是 672 条）。
        self._db = db if db is not None else get_database()
        # 搜索缓存：见 _search_cache_for。只保留最近一个目标色，内存有界。
        self._search_cache: dict = {}
        self._search_cache_key: Optional[tuple] = None

    @property
    def db(self) -> PaintDatabase:
        return self._db

    # ------------------------------------------------------------------ 候选
    def candidate_pool(self, config: AppConfig,
                       brands: Optional[Sequence[str]] = None) -> List[PaintEntry]:
        """按品牌范围 + 可调和性过滤出候选池。

        ``brands`` 的三种取值语义**必须**区分开（此前用 ``brands or None`` 把它们
        糊成一种，导致 UI 上的「全部品牌」实际只搜首选品牌）：

        * ``None`` —— 调用方没指定，沿用 ``config.preferred_brands``；
        * ``[]``   —— 明确要求"不限品牌"，用全库；
        * ``[...]``—— 只用列出的品牌。
        """
        if brands is None:
            requested = list(config.preferred_brands)
        else:
            requested = [key for key in brands if key]
        # 未注册的品牌键（品牌改名、手改配置拼错、旧配置残留）在 by_brands 里会被
        # 静默忽略。这里显式剔除并留痕，同时保留「点名了品牌但一个都不存在 = 无候选」
        # 的既有语义——不能悄悄放开成全库，那等于把用户的品牌限制悄悄取消掉。
        unknown = [key for key in requested if key not in BRANDS]
        if unknown:
            # 每次 suggest 都会走到这里，同一条警告刷几十遍只会把日志刷满
            # （日志文件 1 MB 就轮转）。同一批键只提醒一次。
            fresh = [key for key in unknown if key not in _warned_unknown_brands]
            if fresh:
                _warned_unknown_brands.update(fresh)
                logger.warning("忽略未注册的品牌键: %s（可用品牌见 app/data/brands.py）",
                               "、".join(sorted(fresh)))
        keys = [key for key in requested if key in BRANDS]
        if requested and not keys:
            logger.warning("品牌范围里的键全部未注册，按无候选处理")
            return []
        pool = self._db.by_brands(keys) if keys else list(self._db.entries)
        filtered = [entry for entry in pool
                    if entry.is_mixable(config.allow_metallic_in_mix, config.allow_clear_in_mix)]
        if not filtered:  # 过滤后为空时退回未过滤结果，保证永远有建议可用
            logger.warning("过滤后无可调和色号，回退到品牌全集")
            filtered = pool
        return filtered

    def rank_by_distance(self, target_lab: Sequence[float], pool, formula: str,
                         limit: int) -> List[Tuple[float, PaintEntry]]:
        # 按全库条数跑的单色排序：公式解析一次即可，逐条 delta_e() 会重复做字符串处理
        de_fn = resolve_delta_e(formula)
        scored = [(de_fn(entry.lab, target_lab), entry) for entry in pool]
        scored.sort(key=lambda item: item[0])
        return scored[: max(1, limit)]

    def _search_cache_for(self, target_lab: Sequence[float], config: AppConfig) -> dict:
        """取本次搜索用的缓存（必要时重建）。

        缓存内容是「某个色号对/三元组在该目标色下的最优配比」，它只取决于
        **目标色 + 混合模型 + 色差公式**——与容差、总滴数、候选池组成都无关：
        容差只是拿结果去比较，池子换了同一对色号的最优配比还是那个。

        因此可以安全地跨多次 ``suggest`` 复用。收益最明显的是「用量参数」页：
        拖面积/层数/稀释比会触发整段重算，但搜索输入一个字都没变，整段直接命中。

        只保留最近一个目标色的缓存（界面同时只处理一个取色），换目标色整体丢弃，
        内存有界；即使多个工作线程交替用不同目标色，最坏也只是各自少命中，
        不会读到别人的缓存（每次调用都持有自己那份 dict 的引用）。
        """
        key = (tuple(round(float(v), 6) for v in target_lab),
               config.mixing_model, config.delta_e_formula)
        if self._search_cache_key != key:
            self._search_cache = {}
            self._search_cache_key = key
        return self._search_cache

    def _candidate_pools(self, ranked_all, pool, limit):
        """把候选池切成三层，并预转线性光。

        返回 ``(ranked, nearest_pool, compatible_pools, linear_of)``：

        * ``ranked`` —— 全局最近的若干条（供锚点遍历）；
        * ``nearest_pool`` —— 全局前 ``MATCH_POOL_SIZE`` 条（跨品牌混配时用）；
        * ``compatible_pools`` —— 每个产品线各自最近的 ``MATCH_POOL_SIZE`` 条，
          避免全库前 16 条被其他产品线占满；
        * ``linear_of`` —— ``{uid: 线性光}`` 预计算表，后续每个锚点直接查表复用，
          不再对同一批候选反复做 RGB→线性光转换（suggest 的主要耗时点）。
        """
        ranked = ranked_all[:max(MATCH_POOL_SIZE, limit * 3)]
        nearest_pool = [entry for _, entry in ranked[:MATCH_POOL_SIZE]]
        compatible_pools: Dict[str, list] = {}
        for _, entry in ranked_all:
            group = compatible_pools.setdefault(entry.brand_key, [])
            if len(group) < MATCH_POOL_SIZE:
                group.append(entry)
        linear_of = {entry.uid: rgb_to_linear(entry.rgb) for entry in pool}
        return ranked, nearest_pool, compatible_pools, linear_of

    # ------------------------------------------------------------------ 主入口
    def suggest(self,
                target_rgb: Sequence[int],
                config: AppConfig,
                brands: Optional[Sequence[str]] = None,
                coverage_input: Optional[CoverageInput] = None,
                max_results: Optional[int] = None) -> List[PaintSuggestion]:
        """生成配色建议列表（按 ΔE 升序）。

        ``brands`` 语义见 :meth:`candidate_pool`（``None`` = 首选品牌，``[]`` = 全库）。
        """
        # 防御性归一化：夹紧到 0-255 整数三元组，避免浮点/越界目标色把下游转换搞崩
        target_rgb = normalize_rgb(target_rgb)
        target_lab = rgb_to_lab(target_rgb)
        # 只有 None 才表示「用配置里的默认条数」；0 / 负数表示「一条都不要」。
        # 此前写成 ``max_results or config.max_suggestions``，把 0 当成没传，
        # 调用方明确要求空结果却拿到 6 条——是个安静的反直觉行为。
        limit = config.max_suggestions if max_results is None else int(max_results)
        if limit <= 0:
            return []
        pool = self.candidate_pool(config, brands)
        if not pool:
            logger.warning("色号库为空或品牌范围无匹配")
            return []

        # 替代色号的检索范围跟随本次的品牌范围，避免「搜全库、替代色却只看 5 家」的割裂
        if brands is None:
            brand_scope = list(config.preferred_brands) or None
        else:
            brand_scope = [key for key in brands if key] or None

        ranked_all = self.rank_by_distance(target_lab, pool, config.delta_e_formula, len(pool))
        ranked, nearest_pool, compatible_pools, linear_of = self._candidate_pools(
            ranked_all, pool, limit)
        # 各锚点的候选池高度重叠（同一品牌下只是把锚点换到队首），色号对/三元组的
        # 搜索结果可以跨锚点复用；再往上抬一层，同一目标色的**多次** suggest 也能复用
        # （改面积/层数/稀释比、调容差都会重算，但搜索输入没变）。
        pair_cache = self._search_cache_for(target_lab, config)

        suggestions: List[PaintSuggestion] = []
        used_keys: set = set()

        # 多取一些锚点，避免去重后凑不满 limit 条
        for rank, (distance, anchor) in enumerate(ranked[: limit * 3], start=1):
            if len(suggestions) >= limit:
                break
            suggestion = self._build_suggestion(
                anchor=anchor,
                target_lab=target_lab,
                nearest_pool=(nearest_pool if config.allow_cross_brand_mix
                              else compatible_pools[anchor.brand_key]),
                config=config,
                linear_of=linear_of,
                coverage_input=coverage_input,
                is_primary=(rank == 1),
                used_keys=used_keys,
                brand_scope=brand_scope,
                pair_cache=pair_cache,
            )
            if suggestion is not None:
                suggestions.append(suggestion)

        # 先按最终执行配方的色差排序，再统一重排名次。
        suggestions.sort(key=lambda item: (item.delta_e, len(item.recipe.components), item.recipe.key))
        for index, item in enumerate(suggestions, start=1):
            item.rank = index
        return suggestions

    def _build_suggestion(self, anchor: PaintEntry, target_lab, nearest_pool,
                         config: AppConfig, linear_of: dict,
                         coverage_input: Optional[CoverageInput],
                         is_primary: bool,
                         used_keys: set,
                         brand_scope: Optional[Sequence[str]] = None,
                         pair_cache: Optional[dict] = None) -> Optional[PaintSuggestion]:
        """为单个锚点构造一条建议；返回 ``None`` 表示该锚点被跳过（无解/重复）。"""
        recipe = self._solve_for(target_lab, anchor, nearest_pool, config,
                                is_primary=is_primary, linear_of=linear_of,
                                pair_cache=pair_cache)
        if recipe is None:
            return None
        key = recipe.key
        if key in used_keys:
            return None
        used_keys.add(key)

        # 卡片上的主色号必须和配方一致，否则会出现
        # 「标题写 AK11035、配方却是两支 AV」的割裂感
        display = self._display_anchor(recipe, anchor)
        coverage = self._estimate(recipe, config, coverage_input)
        alternatives = find_alternatives(
            display, self._db,
            limit=4,
            tolerance=config.match_tolerance,
            formula=config.delta_e_formula,
            brand_scope=brand_scope,
            # 排除本配方已用到的组分，避免「替代色号」里又出现配方自身
            exclude=[comp.paint.uid for comp in recipe.components],
        )
        components = [comp.paint for comp in recipe.components] or [display]
        return PaintSuggestion(
            rank=0,  # 由调用方在追加后统一重排
            anchor=display,
            delta_e=recipe.delta_e,
            grade=grade_delta_e(recipe.delta_e),
            recipe=recipe,
            coverage=coverage,
            alternatives=alternatives,
            notes=self._notes(recipe, config, coverage),
            tolerance=config.match_tolerance,
            provenance=provenance_of(components, alternatives),
        )

    # ------------------------------------------------------------------ 内部
    def _solve_for(self, target_lab, anchor: PaintEntry, pool, config: AppConfig,
                   is_primary: bool, linear_of: dict,
                   pair_cache: Optional[dict] = None) -> Optional[Recipe]:
        """为主锚点求解配方。首要建议允许 3 色，其余限制 2 色以控制计算量。

        ``linear_of`` 为 ``{entry: 线性光}`` 预计算表，由 ``suggest`` 一次性构建后复用。
        """
        max_components = config.max_recipe_components if is_primary else min(2, config.max_recipe_components)
        if not anchor.is_mixable(config.allow_metallic_in_mix, config.allow_clear_in_mix):
            return build_direct_recipe(anchor, target_lab, config.delta_e_formula)
        pool = [entry for entry in pool
                if entry.is_mixable(config.allow_metallic_in_mix, config.allow_clear_in_mix)
                and (config.allow_cross_brand_mix or entry.brand_key == anchor.brand_key)]
        candidates = self._pool_for(anchor, pool, size=MATCH_POOL_SIZE)
        # linear_of 只覆盖最近的 MATCH_POOL_SIZE 个候选，而主循环可能扫到第 limit*3 个锚点；
        # 当去重较多、迟迟凑不满 limit 时，锚点会落到线性表之外。用 get(...) 兜底再即时转换，
        # 避免这里抛 KeyError 让整次 suggest 崩掉。
        prepared = [
            (entry, linear_of.get(entry.uid) or rgb_to_linear(entry.rgb))
            for entry in candidates
        ]
        recipe = solve_recipe(
            target_lab=target_lab,
            candidates=candidates,
            max_components=max_components,
            model=config.mixing_model,
            formula=config.delta_e_formula,
            drop_total=config.drop_total,
            tolerance=config.match_tolerance,
            prepared=prepared,
            pair_cache=pair_cache,
        )
        if recipe is None:
            return build_direct_recipe(anchor, target_lab, config.delta_e_formula)
        # 非首要建议必须锚定在自己那个色号上，否则去重后列表会被同一方案占满
        if not is_primary and all(comp.paint.uid != anchor.uid for comp in recipe.components):
            return build_direct_recipe(anchor, target_lab, config.delta_e_formula)
        return recipe

    @staticmethod
    def _display_anchor(recipe: Recipe, fallback: PaintEntry) -> PaintEntry:
        """让建议卡片的「主色号」与配方保持一致：取占比最大的组分。"""
        if any(comp.paint.uid == fallback.uid for comp in recipe.components):
            return fallback
        if not recipe.components:
            return fallback
        return max(recipe.components, key=lambda comp: comp.proportion).paint

    @staticmethod
    def _pool_for(anchor: PaintEntry, pool: Sequence[PaintEntry], size: int) -> List[PaintEntry]:
        """把锚点放到候选池首位，保证它一定参与搜索。"""
        out: List[PaintEntry] = [anchor]
        for entry in pool:
            if entry.uid != anchor.uid:
                out.append(entry)
            if len(out) >= size:
                break
        return out

    def _estimate(self, recipe: Recipe, config: AppConfig,
                  coverage_input: Optional[CoverageInput]) -> CoverageEstimate:
        inp = coverage_input or CoverageInput(
            area_m2=config.area_m2,
            coats=config.coats,
            thinner_ratio=config.thinner_ratio,
            application=config.application,
            surface=config.surface,
            mix_ml_per_m2_per_coat=config.mix_ml_per_m2_per_coat,
            waste_buffer=config.waste_buffer,
            fixed_paint_loss_ml=config.fixed_paint_loss_ml,
        )
        anchor = recipe.components[0].paint
        coats = max(suggest_coats(c.paint.finish, c.paint.opacity, inp.coats)
                    for c in recipe.components)
        thinner_ratio = inp.thinner_ratio
        if (config.auto_prethinned and inp.application == "airbrush"
                and all(c.paint.brand and c.paint.brand.pre_thinned for c in recipe.components)):
            thinner_ratio = 0.0
        # 用 dataclasses.asdict 构造副本而非 inp.__dict__，避免依赖内部实现且更可读
        tuned = CoverageInput(**{**asdict(inp), "coats": coats, "thinner_ratio": thinner_ratio})
        proportions: Dict[str, float] = {
            comp.paint.uid: comp.proportion for comp in recipe.components
        }
        # 单色配方按该色号瓶装容量折算瓶数；多色配方没有单一容量，瓶数留空
        bottle_ml = anchor.volume_ml if len(recipe.components) == 1 else 0.0
        return estimate_coverage(tuned, proportions, bottle_ml)

    @staticmethod
    def _notes(recipe: Recipe, config: AppConfig, coverage: CoverageEstimate) -> List[str]:
        notes: List[str] = []
        for comp in recipe.components:
            if comp.paint.opacity == "semi":
                notes.append(f"{comp.paint.code} 遮盖力偏弱，建议先喷白/灰底")
                break
        if recipe.direct:
            label = ("单色匹配在容差内，无需混色" if recipe.delta_e <= config.match_tolerance
                     else "单色近似（色差偏大），无需混色但需接受色偏")
            notes.append(f"{label}；预测色差 {format_delta_e(recipe.delta_e)}")
        else:
            drops = recipe.drops_text()
            notes.append(f"按 {drops} 滴配比调匀（{recipe.percent_text()}）")
        if recipe.components:
            brands = {comp.paint.brand_key for comp in recipe.components}
            if len(brands) > 1:
                names = "、".join(BRANDS[b].short for b in sorted(brands) if b in BRANDS)
                notes.append(f"跨品牌混用（{names}），兼容性未验证，请先小量试混确认相容性")
            else:
                brand = recipe.components[0].paint.brand
                if brand:
                    notes.append(f"产品线稀释参考：{brand.thinner}")
                    if brand.pre_thinned:
                        notes.append("此产品已预稀释；纯漆用量指瓶装原液，自动模式不另加稀释剂")
        notes.append("颜色与ΔE为数字色卡近似预测；底漆、膜厚、光泽会影响实喷结果，请先试喷")
        notes.extend(coverage.notes)
        return notes


def summarize(suggestions: Sequence[PaintSuggestion]) -> str:
    """给状态栏/导出用的一句话摘要。"""
    if not suggestions:
        return "暂无建议"
    best = suggestions[0]
    # 保留两位：卡片上写 ΔE 2.96、状态栏写 3.0 会让人以为是两次不同的计算
    if best.is_direct:
        return f"最接近：{best.anchor.full_label}（{format_delta_e(best.delta_e)}）"
    return f"推荐调配：{best.recipe.components_text()}（{format_delta_e(best.delta_e)}）"
