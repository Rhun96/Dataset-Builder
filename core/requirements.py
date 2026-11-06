"""Требования к выборке: размер, фильтры, квоты. Структуры, не SQL-строки."""

from __future__ import annotations

from dataclasses import dataclass, field

FILTER_OPS = ("eq", "ne", "in", "notin", "missing", "notmissing",
              "contains", "gt", "lt")

# Пользовательские подписи (русский интерфейс, без латиницы в глаза).
SEED_LABEL = "Вариант выборки"
SEED_HINT = ("Число от 0 до 999999. Одинаковые требования и то же число "
             "дают ту же выборку: например, 1, 2 и 3 — три разных набора. "
             "Поменяй число, чтобы получить другой вариант.")


def profile_to_dict(profile: BuildProfile) -> dict:
    from dataclasses import asdict
    return asdict(profile)


def profile_from_dict(data: dict) -> BuildProfile:
    return BuildProfile(
        target_size=data.get("target_size", 0),
        seed=data.get("seed", 0),
        mode=data.get("mode", "quota"),
        filters=[Filter(**f) for f in data.get("filters", [])],
        quotas=[Quota(**q) for q in data.get("quotas", [])],
        stratify_dim=data.get("stratify_dim", ""),
        max_source_pct=data.get("max_source_pct", 0),
        exclude_builds=data.get("exclude_builds", []),
        min_new=data.get("min_new", 0),
        keep_build=data.get("keep_build"),
        keep_min=data.get("keep_min", 0),
        div_threshold=data.get("div_threshold", 0),
        rarity=data.get("rarity", False),
    )


@dataclass
class Filter:
    dim: str
    op: str
    value: str = ""
    values: list[str] = field(default_factory=list)

    def validate(self):
        if self.op not in FILTER_OPS:
            raise ValueError(f"неизвестный оператор {self.op!r}")
        if self.op in ("in", "notin") and not self.values:
            raise ValueError("in/notin требует список значений")
        if self.op in ("eq", "ne", "contains", "gt", "lt") and not self.value:
            raise ValueError(f"{self.op} требует значение")


@dataclass
class Quota:
    dim: str
    value: str  # norm-значение ячейки
    kind: str   # min | max | exact | percent
    amount: float
    dim2: str = ""    # второе измерение; пусто — квота по одному полю
    value2: str = ""  # значение второго измерения

    def validate(self):
        if self.kind not in ("min", "max", "exact", "percent"):
            raise ValueError(f"неизвестный вид квоты {self.kind!r}")
        if self.amount < 0:
            raise ValueError("квота не может быть отрицательной")
        if self.kind == "percent" and self.amount > 100:
            raise ValueError("процент не больше 100")
        if bool(self.dim2) != bool(self.value2):
            raise ValueError("пара «измерение 2 = значение 2» заполняется целиком")

    def label(self) -> str:
        base = f"{self.dim}={self.value}"
        if self.dim2:
            base += f" + {self.dim2}={self.value2}"
        return base


@dataclass
class BuildProfile:
    target_size: int = 500
    seed: int = 42
    mode: str = "quota"  # random | quota | stratified
    filters: list[Filter] = field(default_factory=list)
    quotas: list[Quota] = field(default_factory=list)
    stratify_dim: str = ""  # для mode=stratified
    max_source_pct: float = 0  # 0 — без лимита доли источника
    exclude_builds: list[int] = field(default_factory=list)
    min_new: int = 0  # не менее N новых (вне exclude_builds)
    keep_build: int | None = None
    keep_min: int = 0
    div_threshold: float = 0  # 0 — выкл; иначе макс. сходство Жаккара 0.5–0.99
    rarity: bool = False  # сначала редкие сочетания значений

    def validate(self):
        if self.target_size <= 0:
            raise ValueError("целевой размер должен быть > 0")
        if self.mode not in ("random", "quota", "stratified", "mixed"):
            raise ValueError(f"неизвестный режим {self.mode!r}")
        for f in self.filters:
            f.validate()
        for q in self.quotas:
            q.validate()
        if self.mode == "stratified" and not self.stratify_dim:
            raise ValueError("стратификация требует измерение")
        if not 0 <= self.max_source_pct <= 100:
            raise ValueError("доля источника — 0–100")
        if not 0 <= self.div_threshold <= 0.99:
            raise ValueError("порог сходства — 0 (выкл) или 0.5–0.99")
        if self.div_threshold and self.div_threshold < 0.5:
            raise ValueError("порог ниже 0.5 выкинет почти всё — поставь 0.8–0.9")
        if self.min_new < 0 or self.min_new > self.target_size:
            raise ValueError("«не менее новых» — от 0 до цели")
        if self.keep_min < 0 or self.keep_min > self.target_size:
            raise ValueError("«сохранить» — от 0 до цели")
