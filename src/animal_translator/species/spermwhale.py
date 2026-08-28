"""Разбор сигналов кашалота.

Значение коды не установлено наукой, поэтому оно не выдаётся ни при каком вводе.
Строение коды при этом измеряется. У обычных щелчков функция известна, и для них
ответ есть.

Разбор разведён на два уровня:
  что за сигнал  — тип щелчков связан с деятельностью, репертуар код с кланом
  что сказано    — не установлено ни для одной коды
"""

from __future__ import annotations

from typing import Any

from ..knowledge import load_species
from ..result import Result, Step, Unknown, UnknownKind, Verdict

SLUG = "spermwhale"


def _describe_structure(kb: dict[str, Any], obs: dict[str, Any]) -> tuple[list[Step], list[Unknown]]:
    """Измеряет четыре признака коды по вводу. Номерной тип не присваивается."""
    structure = kb["structure"]
    labels = {f["id"]: f for f in structure["features"]}
    steps: list[Step] = []
    gaps: list[Unknown] = []

    intervals = obs.get("inter_click_intervals_s")
    if intervals:
        total = sum(intervals)
        normalised = [round(i / total, 3) for i in intervals]
        steps.append(Step(
            label_ru=labels["rhythm"]["label_ru"],
            value_ru=f"{len(intervals) + 1} щелчков, нормированный рисунок интервалов {normalised}",
            source_ids=[structure["source_id"]],
        ))
        steps.append(Step(
            label_ru=labels["tempo"]["label_ru"],
            value_ru=f"общая длительность {total:.3f} с",
            source_ids=[structure["source_id"]],
        ))
    else:
        gaps.append(Unknown(
            field_ru="Ритм и темп",
            kind=UnknownKind.DATA_GAP,
            explanation_ru="Не заданы межщелчковые интервалы: без них ни рисунок ритма, ни длительность не измерить.",
        ))

    if obs.get("extra_final_click") is not None:
        present = obs["extra_final_click"]
        steps.append(Step(
            label_ru=labels["ornamentation"]["label_ru"],
            value_ru=("дополнительный щелчок в конце есть" if present else "дополнительного щелчка нет")
                     + f" ({labels['ornamentation']['frequency_ru']})",
            source_ids=[structure["source_id"]],
        ))
    else:
        gaps.append(Unknown(
            field_ru="Орнаментация",
            kind=UnknownKind.DATA_GAP,
            explanation_ru="Не указано, был ли дополнительный щелчок в конце коды.",
        ))

    durations = obs.get("exchange_durations_s")
    if durations and len(durations) >= 2:
        drift = durations[-1] - durations[0]
        steps.append(Step(
            label_ru=labels["rubato"]["label_ru"],
            value_ru=f"длительность по ходу обмена изменилась на {drift:+.3f} с за {len(durations)} повторов",
            source_ids=[structure["source_id"]],
        ))
    else:
        gaps.append(Unknown(
            field_ru="Рубато",
            kind=UnknownKind.BEYOND_MODEL,
            explanation_ru=(
                "Рубато определено только внутри обмена: это изменение длительности от повтора "
                "к повтору. По одной изолированной коде оно не измеряется в принципе."
            ),
        ))

    return steps, gaps


def translate(observation: dict[str, Any]) -> Result:
    kb = load_species(SLUG)
    signal = next((s for s in kb["signals"] if all(observation.get(k) == v for k, v in s["match"].items())), None)

    if signal is None:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Не указан тип сигнала.",
            confidence_level_ru="недостаточно данных",
            unknowns=[Unknown(
                field_ru="Тип сигнала",
                kind=UnknownKind.DATA_GAP,
                explanation_ru="Эхолокационные щелчки и коды — разные вещи: первые служат ориентации, вторые общению.",
            )],
        )

    # Эхолокация: функция сигнала известна, и это единственный случай у вида,
    # где ответ содержателен.
    if signal["has_meaning"]:
        steps = [Step(label_ru=signal["label_ru"], value_ru=signal["meaning_kind_ru"],
                      source_ids=signal["source_ids"])]
        for fact in signal.get("supporting_facts_ru", []):
            steps.append(Step(label_ru="Измерено", value_ru=fact,
                              source_ids=[signal["measured_quantity"]["source_id"]]))

        measured = signal.get("measured_quantity")
        return Result(
            species=SLUG,
            verdict=Verdict.TRANSLATED,
            headline_ru=signal["behaviour_ru"],
            confidence=measured["value"] if measured else None,
            confidence_level_ru="функция установлена измерениями",
            confidence_scope_ru=measured["label_ru"] if measured else None,
            steps=steps,
            unknowns=[],
            warnings_ru=[
                "Это функция сигнала, а не содержание сообщения: щелчок направлен на добычу и среду, "
                "а не на сородича.",
                measured["scope_ru"] if measured else "",
            ],
            source_ids=signal["source_ids"],
        )

    # Кода: структура разбирается, значение — нет.
    steps, gaps = _describe_structure(kb, observation)
    steps.insert(0, Step(
        label_ru="Что за сигнал",
        value_ru=signal["behaviour_ru"],
        source_ids=signal["source_ids"],
    ))

    meaning = kb["levels"]["meaning_level"]
    inventory = kb["structure"]["inventory"]
    source = next(s for s in kb["sources"] if s["id"] == "sharma2024")

    gaps.append(Unknown(
        field_ru="Что сказано",
        kind=UnknownKind.NOT_ENCODED,
        explanation_ru=(
            f"{meaning['why_ru']} Дополнительные наблюдения этого не изменят: значение не установлено "
            "не для этой записи, а ни для одной коды вообще."
        ),
    ))

    return Result(
        species=SLUG,
        verdict=Verdict.NO_TRANSLATION_EXISTS,
        headline_ru="Структура коды разобрана. Значения у неё не установлено ни одного.",
        confidence=None,
        confidence_level_ru="перевода не существует",
        steps=steps,
        unknowns=gaps,
        alternatives_ru=[],
        warnings_ru=[
            source["authors_own_limit_ru"],
            f"Описано не менее {inventory['combinations_found']} часто встречающихся сочетаний ритма и темпа. "
            f"Ранее репертуар оценивали примерно в {inventory['previously_described_types']} отдельных типов коды. "
            "Богатство репертуара измерено, содержание — нет.",
            kb["structure"]["classification_limit_ru"],
            "Единственное значение, надёжно связанное с кодами, — принадлежность к вокальному клану, "
            "то есть кто говорит, а не что сказано.",
        ],
        source_ids=signal["source_ids"],
    )
