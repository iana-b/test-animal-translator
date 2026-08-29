"""Разбор сигналов африканского саванного слона.

Трактовки различаются не вероятностью, а тем, каким экспериментом подкреплены.
Значение, проверенное проигрыванием записи живым слонам (Poole 1999), стоит
выше значения, известного только по совместной встречаемости с ситуацией,
и последнее не может его вытеснить.

Отдельно учитывается, что основная частота рёва лежит частично ниже порога
человеческого слуха: наблюдение, сделанное только на слух, заведомо неполно.
"""

from __future__ import annotations

from typing import Any

from ..knowledge import load_species
from ..result import Result, Step, Unknown, UnknownKind, Verdict

SLUG = "elephant"


def _tier_rank(kb: dict[str, Any], tier_id: str) -> int:
    return next(t["rank"] for t in kb["evidence_tiers"]["levels"] if t["id"] == tier_id)


def _tier_label(kb: dict[str, Any], tier_id: str) -> str:
    return next(t["label_ru"] for t in kb["evidence_tiers"]["levels"] if t["id"] == tier_id)


def _matches(signal: dict[str, Any], obs: dict[str, Any]) -> bool:
    return all(obs.get(k) == v for k, v in signal["match"].items())


def _support_count(signal: dict[str, Any], obs: dict[str, Any]) -> int:
    return sum(1 for k, v in signal.get("supporting", {}).items() if obs.get(k) == v)


def _hearing_warning(kb: dict[str, Any], obs: dict[str, Any]) -> Unknown | None:
    """Наблюдение только на слух не покрывает основную частоту рёва."""
    hearing = kb["human_hearing"]
    if obs.get("f0_hz") is not None:
        return None
    if obs.get("perceived") != "heard":
        return None
    lo, hi = hearing["f0_range_hz"]
    return Unknown(
        field_ru="Основная частота",
        kind=UnknownKind.DATA_GAP,
        explanation_ru=(
            f"Наблюдение записано только на слух. Основная частота рёва лежит в диапазоне "
            f"{lo}–{hi} Гц, а слух человека начинается примерно с {hearing['human_hearing_floor_hz']} Гц: "
            "часть сигнала не воспринята. Нужна запись с измерением частоты."
        ),
    )


def translate(observation: dict[str, Any]) -> Result:
    kb = load_species(SLUG)

    if observation.get("perceived") == "not_perceived" and observation.get("f0_hz") is None:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Сигнал не зафиксирован: разбирать нечего.",
            confidence_level_ru="недостаточно данных",
            unknowns=[
                Unknown(
                    field_ru="Сам сигнал",
                    kind=UnknownKind.DATA_GAP,
                    explanation_ru=(
                        "Ни измерения частоты, ни восприятия на слух или через вибрацию. "
                        "Значительная часть общения слонов проходит ниже порога человеческого слуха."
                    ),
                )
            ],
            source_ids=[kb["human_hearing"]["source_id"]],
        )

    candidates = [s for s in kb["signals"] if _matches(s, observation)]

    if not candidates:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Ни один описанный тип сигнала не подошёл под наблюдение.",
            unknowns=[
                Unknown(
                    field_ru="Тип сигнала",
                    kind=UnknownKind.DATA_GAP,
                    explanation_ru=(
                        "Различающие признаки — тряска головой, реакция группы, наличие угрозы, "
                        "разлука или воссоединение — не заполнены или не совпали ни с одним описанием."
                    ),
                )
            ],
            source_ids=[s["id"] for s in kb["sources"][:1]],
        )

    # Сначала уровень доказательности, затем число совпавших вспомогательных признаков.
    candidates.sort(
        key=lambda s: (_tier_rank(kb, s["evidence_tier"]), _support_count(s, observation)),
        reverse=True,
    )
    best = candidates[0]
    tier = best["evidence_tier"]

    steps = [
        Step(
            label_ru="Уровень доказательности",
            value_ru=f"{_tier_label(kb, tier)}. "
                     + next(t["meaning_ru"] for t in kb["evidence_tiers"]["levels"] if t["id"] == tier),
            source_ids=[kb["evidence_tiers"]["source_id"]],
        ),
        Step(label_ru="Различающий признак", value_ru=best["discriminator_ru"], source_ids=best["source_ids"]),
    ]
    if best.get("acoustic_ru"):
        steps.append(Step(label_ru="Акустика", value_ru=best["acoustic_ru"], source_ids=best["source_ids"]))

    warnings: list[str] = []
    confidence = None
    scope = None

    playback = best.get("playback_response")
    if playback:
        rate = playback["retreated"] / playback["of_trials"]
        control = playback["control_retreated"] / playback["control_of_trials"]
        confidence = rate
        scope = "столько семей слонов ответили ожидаемым образом, когда им проиграли запись"
        steps.append(
            Step(
                label_ru="Реакция на проигрывание",
                value_ru=(
                    f"{playback['retreated']} семей из {playback['of_trials']} ушли, услышав запись "
                    f"({rate:.0%}). На собственный спокойный рёв, записанный до опыта, ушли "
                    f"{playback['control_retreated']} из {playback['control_of_trials']} "
                    f"({control:.0%}) — значит, дело в самом сигнале."
                ),
                source_ids=[playback["source_id"]],
            )
        )
        warnings.append(
            "Уверенность здесь — не оценка правдоподобия трактовки, а измеренная доля слонов, "
            "ответивших на запись ожидаемым образом. Даже при верной трактовке она заметно ниже единицы."
        )
    elif tier == "playback_verified":
        warnings.append(
            "Значение проверено проигрыванием, но числовой доли отклика для этого сигнала "
            "в используемых источниках нет, поэтому процент не выводится."
        )
    else:
        warnings.append(
            "Значение известно только по совместной встречаемости с ситуацией: запись слонам "
            "не проигрывали. Название сигнала описывает обстановку наблюдения, а не проверенный смысл."
        )

    unknowns = []
    hearing = _hearing_warning(kb, observation)
    if hearing:
        unknowns.append(hearing)

    outranked = [c for c in candidates[1:] if _tier_rank(kb, c["evidence_tier"]) < _tier_rank(kb, tier)]
    if outranked:
        warnings.append(
            "Ниже по доказательности также подошли: "
            + ", ".join(f"«{c['label_ru']}» ({_tier_label(kb, c['evidence_tier']).lower()})" for c in outranked)
            + ". Такие трактовки не могут вытеснить проверенную проигрыванием."
        )

    verdict = Verdict.TRANSLATED if tier == "playback_verified" else Verdict.PARTIAL

    # Шкала «низкая/средняя/высокая» описывает правдоподобие трактовки. Доля отклика на
    # проигрывание — величина другого рода, и под эту шкалу не подводится.
    if tier == "playback_verified":
        level = "проверено проигрыванием"
    else:
        level = "только связь с контекстом"

    return Result(
        species=SLUG,
        verdict=verdict,
        headline_ru=best["translation_ru"],
        confidence=confidence,
        confidence_level_ru=level,
        confidence_scope_ru=scope,
        steps=steps,
        unknowns=unknowns,
        alternatives_ru=best["alternatives_ru"] + [c["label_ru"] for c in candidates[1:]],
        warnings_ru=warnings,
        source_ids=best["source_ids"],
    )
