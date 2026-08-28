"""Разбор сигналов домашней собаки.

Контекст лая оценивается вероятностно: акустика разделяет ситуации ограниченно,
и величина этого ограничения измерена в Molnár et al. 2008.

Ход разбора:
  слышимые признаки → эмоциональный профиль (Pongrácz 2006)
  → контексты-кандидаты
  → распределение по всем шести контекстам через матрицу путаницы (Molnár 2008)
  → проверка, отличается ли распознавание верхнего контекста от случайного
"""

from __future__ import annotations

from typing import Any

from ..knowledge import load_species
from ..result import Result, Step, Unknown, UnknownKind, Verdict, confidence_level_ru

SLUG = "dog"

ACOUSTIC_FIELDS = ("pitch", "repetition", "tonality")



def _match_profile(kb: dict[str, Any], obs: dict[str, Any]) -> tuple[dict | None, Unknown | None]:
    """Возвращает подошедший эмоциональный профиль либо причину, по которой он не определён."""
    pitch, rep, tone = (obs.get(f) for f in ACOUSTIC_FIELDS)

    if pitch is None or rep is None:
        return None, Unknown(
            field_ru="Высота тона и частота повторения",
            kind=UnknownKind.DATA_GAP,
            explanation_ru=(
                "Эмоциональный профиль лая строится на высоте тона и частоте повторения. "
                "Без них нельзя выбрать даже направление трактовки."
            ),
        )

    profiles = kb["acoustic_rules"]["profiles"]

    if pitch == "high" and rep == "slow" and tone is None:
        # Тональность разделяет страх и игривость; без неё рассматриваются оба семейства.
        merged = {
            "id": "high_slow_ambiguous",
            "label_ru": "Высокий и редкий лай, тональность не указана",
            "candidates": ["alone", "play", "ball"],
            "evidence_ru": (
                "Высокий редкий лай означает либо страх и отчаяние (если звук чистый), "
                "либо радость и игривость (если шероховатый). Тональность здесь решающая."
            ),
        }
        return merged, Unknown(
            field_ru="Тональность",
            kind=UnknownKind.DATA_GAP,
            explanation_ru=(
                "Чистый звук или шероховатый — именно этот признак отделяет страх от игривости. "
                "Укажите его, и трактовка сузится вдвое."
            ),
        )

    for p in profiles:
        if all(obs.get(k) == v for k, v in p["match"].items()):
            return p, None

    return None, Unknown(
        field_ru="Сочетание признаков",
        kind=UnknownKind.BEYOND_MODEL,
        explanation_ru=(
            "Такое сочетание высоты, тональности и ритма в опубликованных шкалах не описано. "
            "Это не пробел наблюдения: измерения есть, но их сочетание за пределами изученного."
        ),
    )


def _posterior(kb: dict[str, Any], candidates: list[str], obs: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
    """Априор × правдоподобие из матрицы путаницы, нормированные."""
    rows = kb["confusion_matrix"]["rows"]
    contexts = [c["id"] for c in kb["contexts"]]
    notes: list[str] = []

    prior = {c: 1.0 for c in contexts}

    reported = obs.get("reported_situation")
    if reported in contexts:
        weight = kb["decision_rules"]["situation_prior_weight"]
        prior[reported] *= weight
        notes.append(
            f"сообщённая ситуация «{next(c['label_ru'] for c in kb['contexts'] if c['id'] == reported)}» "
            f"поднимает её априорный вес в {weight:.0f} раза"
        )

    if obs.get("play_bow"):
        for c in ("play", "ball"):
            prior[c] *= kb["decision_rules"]["play_bow_prior_weight"]
        notes.append("игровой поклон повышает вес игровых контекстов")

    total_prior = sum(prior.values())
    prior = {c: v / total_prior for c, v in prior.items()}

    scores = {}
    for ctx in contexts:
        likelihood = sum(rows[ctx][c] for c in candidates) / len(candidates)
        scores[ctx] = prior[ctx] * likelihood

    total = sum(scores.values())
    if total == 0:
        return {c: 0.0 for c in contexts}, notes
    return {c: v / total for c, v in scores.items()}, notes


def _completeness(kb: dict[str, Any], obs: dict[str, Any]) -> float:
    """Поправка на незаполненные акустические признаки."""
    floor = kb["decision_rules"]["completeness_floor"]
    filled = sum(1 for f in ACOUSTIC_FIELDS if obs.get(f) is not None)
    return floor + (1 - floor) * (filled / len(ACOUSTIC_FIELDS))


def _growl(kb: dict[str, Any], obs: dict[str, Any]) -> Result:
    rules = kb["growl_rules"]
    pitch, duration = obs.get("pitch"), obs.get("duration")

    if pitch is None:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Рычание распознано, но тип не определить.",
            unknowns=[
                Unknown(
                    field_ru="Высота тона",
                    kind=UnknownKind.DATA_GAP,
                    explanation_ru="Игровое рычание отличается от агрессивного прежде всего высотой и длительностью.",
                )
            ],
            source_ids=[rules["source_id"]],
        )

    matched = next(
        (t for t in rules["types"] if t["match"]["pitch"] == pitch
         and (duration is None or t["match"]["duration"] == duration)),
        None,
    )
    if matched is None:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Сочетание признаков рычания не совпало ни с одним описанным типом.",
            source_ids=[rules["source_id"]],
        )

    unknowns = []
    if not matched["separable"]:
        unknowns.append(
            Unknown(
                field_ru="Охрана ресурса или ответ на угрозу",
                kind=UnknownKind.NOT_ENCODED,
                explanation_ru=(
                    "Эти два случая по звуку почти не различаются — акустические различия "
                    "слабые или отсутствуют. Сами собаки их различают, человек по записи — нет. "
                    "Различить поможет только обстановка, а не сам звук."
                ),
            )
        )

    return Result(
        species=SLUG,
        verdict=Verdict.TRANSLATED if matched["separable"] else Verdict.PARTIAL,
        headline_ru=matched["translation_ru"],
        confidence=None,
        confidence_level_ru="высокая (качественная оценка)",
        steps=[Step(label_ru=matched["label_ru"], value_ru=matched["evidence_ru"], source_ids=[rules["source_id"]])],
        unknowns=unknowns,
        source_ids=[rules["source_id"]],
    )


def translate(observation: dict[str, Any]) -> Result:
    kb = load_species(SLUG)
    labels = {c["id"]: c["label_ru"] for c in kb["contexts"]}
    signal = observation.get("signal_type")

    if signal == "growl":
        return _growl(kb, observation)

    if signal in ("whine", "howl"):
        return Result(
            species=SLUG,
            verdict=Verdict.NO_TRANSLATION_EXISTS,
            headline_ru="Для этого сигнала в базе нет измеренной модели.",
            confidence_level_ru="перевода не существует",
            unknowns=[
                Unknown(
                    field_ru="Значение сигнала",
                    kind=UnknownKind.BEYOND_MODEL,
                    explanation_ru=(
                        "База знаний собаки построена на исследованиях лая и рычания. "
                        "Скулёж и вой в них не разбирались, а переносить выводы с лая на них нельзя."
                    ),
                )
            ],
        )

    if signal != "bark":
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Не указан тип сигнала.",
            unknowns=[
                Unknown(
                    field_ru="Тип сигнала",
                    kind=UnknownKind.DATA_GAP,
                    explanation_ru="Лай и рычание разбираются разными наборами исследований.",
                )
            ],
        )

    profile, gap = _match_profile(kb, observation)
    if profile is None:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Лай распознан, но эмоциональный профиль не определить.",
            unknowns=[gap] if gap else [],
            source_ids=[kb["acoustic_rules"]["source_id"]],
        )

    posterior, prior_notes = _posterior(kb, profile["candidates"], observation)
    ranked = sorted(posterior.items(), key=lambda kv: kv[1], reverse=True)
    top_ctx, top_p = ranked[0]

    confidence = top_p * _completeness(kb, observation)
    reliability = kb["reliability"]["per_context"][top_ctx]

    steps = [
        Step(
            label_ru="Эмоциональный профиль",
            value_ru=f"{profile['label_ru']}. {profile['evidence_ru']}",
            source_ids=[kb["acoustic_rules"]["source_id"]],
        ),
        Step(
            label_ru="Кандидаты по профилю",
            value_ru=", ".join(labels[c] for c in profile["candidates"]),
            source_ids=[kb["acoustic_rules"]["source_id"]],
        ),
        Step(
            label_ru="Распределение после поправки на путаницу",
            value_ru="; ".join(f"{labels[c]} — {p:.0%}" for c, p in ranked),
            source_ids=[kb["confusion_matrix"]["source_id"]],
        ),
    ]

    warnings = list(prior_notes)
    warnings.append(kb["confusion_matrix"]["caveat_ru"])

    unknowns = [gap] if gap else []
    second_p = ranked[1][1]

    rules = kb["decision_rules"]
    if confidence < rules["refusal_threshold"]:
        verdict = Verdict.INSUFFICIENT
        headline = (
            "Контекст не определён: ни одна трактовка не набирает "
            f"{rules['refusal_threshold']:.0%}. Ниже показано, что рассматривалось и с какими оценками."
        )
    elif top_p - second_p < rules["ambiguity_gap"]:
        verdict = Verdict.PARTIAL
        headline = (
            f"Неоднозначно: «{labels[top_ctx].lower()}» и «{labels[ranked[1][0]].lower()}» "
            "разошлись слишком мало, чтобы выбрать между ними."
        )
    else:
        verdict = Verdict.TRANSLATED
        headline = f"Вероятнее всего: {labels[top_ctx].lower()}."

    if not reliability["better_than_random"]:
        if verdict is Verdict.TRANSLATED:
            verdict = Verdict.PARTIAL
        warnings.append(
            f"Верхняя трактовка — «{labels[top_ctx]}». В опубликованном тесте распознавание этого "
            f"контекста по звуку статистически не отличалось от случайного ({reliability['p_ru']}), "
            f"а каппа составила {reliability['kappa']:+.0%}. Принимать этот ответ за установленный нельзя."
        )
    else:
        warnings.append(
            f"Для контекста «{labels[top_ctx]}» распознавание по звуку значимо лучше случайного "
            f"({reliability['p_ru']}), полнота {reliability['recall']:.0%}, каппа {reliability['kappa']:+.0%}."
        )

    family = sum(posterior[c] for c in profile["candidates"])
    warnings.append(
        f"Семейство контекстов по этому профилю в сумме даёт {family:.0%} — "
        f"оно надёжнее, чем выбор одного контекста внутри него."
    )

    return Result(
        species=SLUG,
        verdict=verdict,
        headline_ru=headline,
        confidence=confidence,
        confidence_level_ru=confidence_level_ru(confidence),
        confidence_scope_ru="апостериорная вероятность верхнего контекста с поправкой на полноту ввода",
        steps=steps,
        unknowns=unknowns,
        alternatives_ru=[f"{labels[c]} — {p:.0%}" for c, p in ranked[1:4]],
        warnings_ru=warnings,
        source_ids=[kb["acoustic_rules"]["source_id"], kb["confusion_matrix"]["source_id"]],
    )
