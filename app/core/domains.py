"""学科领域包。

设计意图：本应用的主流程（解析 → 提取 → 生成 → 校验 → 渲染）与学科无关，
真正跟学科相关的只有「提示词」这一处。因此把每个学科的提示词打包成一个 DomainPack，
新增学科 = 新增一个 DomainPack 并注册进 _PACKS，主流程一行都不用改。

如何新增一个学科（例如「信号与系统」）：
1. 在 prompt.py 里写两段东西：
   - 可视化素材清单（提取用，如 VISUAL_SIGNAL）
   - 专属技法（生成用，如 TECH_SIGNAL：该用什么 mobject 画采样、频谱、卷积）
   然后用 prompt.generate_system_for("信号与系统", TECH_SIGNAL) 拼出生成提示词，
   用 prompt.extract_system_for / plan_system_for 拼出另外两套 ——
   中文禁令、布局规则、节奏规范这些通用硬规则都在骨架里，不用重抄。
2. 在下面建一个 DomainPack，并加进 _PACKS。
3. 界面下拉会自动出现该选项，无需改动 main_window.py。

注意：数学（MATH）用的是逐条打磨过的独立提示词，没有走 generate_system_for ——
那是因为它的矩阵格式、Transform 陷阱等条目是踩坑踩出来的，改动风险大于收益。

渲染层（Manim + LaTeX）是通用的：函数曲线、受力箭头、向量网格、数组格子、树、图都能画，
所以扩展学科的成本几乎全在提示词上，不在工程上。
"""
from dataclasses import dataclass

from . import prompt


@dataclass(frozen=True)
class DomainPack:
    key: str            # 内部标识，稳定不变
    label: str          # 界面显示名
    subject: str        # 知识点类型的中文名，用于提示文案（如「数学」）
    extract_system: str
    generate_system: str
    fix_system: str
    plan_system: str = ""   # 对话式策划（内容自定义与工作确认）；缺省用通用兜底


MATH = DomainPack(
    key="math",
    label="数学",
    subject="数学",
    extract_system=prompt.EXTRACT_SYSTEM,
    generate_system=prompt.GENERATE_SYSTEM,
    fix_system=prompt.FIX_SYSTEM,
    plan_system=prompt.PLAN_SYSTEM,
)

# 其余学科共用「骨架 + 专属技法」的拼装方式（见 prompt.generate_system_for）：
# 数学那套是逐条踩坑踩出来的，保持原文不动；新学科只在"该画什么、用什么对象画"上分化。
PHYSICS = DomainPack(
    key="physics",
    label="物理",
    subject="物理",
    extract_system=prompt.extract_system_for("物理", prompt.VISUAL_PHYSICS),
    generate_system=prompt.GENERATE_SYSTEM_PHYSICS,
    fix_system=prompt.FIX_SYSTEM,
    plan_system=prompt.plan_system_for("物理", prompt.PLAN_EXAMPLES_PHYSICS),
)

LINALG = DomainPack(
    key="linalg",
    label="线性代数",
    subject="线性代数",
    extract_system=prompt.extract_system_for("线性代数", prompt.VISUAL_LINALG),
    generate_system=prompt.GENERATE_SYSTEM_LINALG,
    fix_system=prompt.FIX_SYSTEM,
    plan_system=prompt.plan_system_for("线性代数", prompt.PLAN_EXAMPLES_LINALG),
)

PROB = DomainPack(
    key="prob",
    label="概率统计",
    subject="概率统计",
    extract_system=prompt.extract_system_for("概率统计", prompt.VISUAL_PROB),
    generate_system=prompt.GENERATE_SYSTEM_PROB,
    fix_system=prompt.FIX_SYSTEM,
    plan_system=prompt.plan_system_for("概率统计", prompt.PLAN_EXAMPLES_PROB),
)

DSA = DomainPack(
    key="dsa",
    label="数据结构",
    subject="数据结构",
    extract_system=prompt.extract_system_for("数据结构", prompt.VISUAL_DSA),
    generate_system=prompt.GENERATE_SYSTEM_DSA,
    fix_system=prompt.FIX_SYSTEM,
    plan_system=prompt.plan_system_for("数据结构", prompt.PLAN_EXAMPLES_DSA),
)


# 顺序 = 界面上学科下拉的顺序：数学放第一（默认），其余按基础课顺序排
_PACKS: dict[str, DomainPack] = {
    p.key: p for p in (MATH, PHYSICS, LINALG, PROB, DSA)
}

DEFAULT_DOMAIN = MATH.key


def list_packs() -> list[DomainPack]:
    """界面下拉的数据源（当前只有数学）。"""
    return list(_PACKS.values())


def get_pack(key: str | None) -> DomainPack:
    """按 key 取领域包；未知或为空时回落到数学，保证老调用不会炸。"""
    return _PACKS.get((key or "").strip().lower(), MATH)


def register(pack: DomainPack):
    """供未来新增学科调用：register(DSA) 即可。"""
    _PACKS[pack.key] = pack
    return pack
