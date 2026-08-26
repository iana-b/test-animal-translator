"""Декодер танца медоносной пчелы.

Единственный вид в базе, где перевод — арифметика. Все коэффициенты берутся
из data/knowledge/honeybee.json, а не зашиты здесь: база знаний остаётся
единственным источником правды, и README можно собирать из неё же.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..knowledge import load_species
from ..result import Result, Step, Unknown, UnknownKind, Verdict, confidence_level_ru

SLUG = "honeybee"

_COMPASS_RU = [
    "С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ",
    "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ",
]

# Интервал расстояния строится как ±2 SD, то есть примерно 95% разброса.
SIGMA_MULTIPLIER = 2.0


def _compass_ru(bearing_deg: float) -> str:
    return _COMPASS_RU[int((bearing_deg % 360) / 22.5 + 0.5) % 16]


@dataclass
class DistanceEstimate:
    metres: float
    low_metres: float
    high_metres: float
    sigma_metres: float
    extrapolated: bool


def _invert_duration(kb: dict[str, Any], duration_s: float) -> tuple[float, float]:
    """Возвращает (расстояние в км, наклон сегмента). Уравнения обращены."""
    model = kb["quantitative_model"]["distance"]
    near, far = model["forward_equations"]
    if duration_s <= model["breakpoint_duration_s"]:
        eq = near
    else:
        eq = far
    km = (duration_s - eq["intercept_s"]) / eq["slope_s_per_km"]
    return km, eq["slope_s_per_km"]


def _sd_for_distance(kb: dict[str, Any], km: float) -> float:
    """SD длительности растёт с расстоянием: интерполяция между двумя точками статьи."""
    sd = kb["quantitative_model"]["distance"]["sd_model"]
    lo_km, hi_km = 0.1, 1.7
    lo_sd, hi_sd = sd["sd_at_100m_s"], sd["sd_at_1700m_s"]
    clamped = min(max(km, lo_km), hi_km)
    frac = (clamped - lo_km) / (hi_km - lo_km)
    return lo_sd + frac * (hi_sd - lo_sd)


def estimate_distance(kb: dict[str, Any], duration_s: float) -> DistanceEstimate | None:
    model = kb["quantitative_model"]["distance"]
    km, slope = _invert_duration(kb, duration_s)
    if km <= 0:
        return None
    sigma_km = _sd_for_distance(kb, km) / slope
    lo_s, hi_s = model["calibrated_range_duration_s"]
    return DistanceEstimate(
        metres=km * 1000,
        low_metres=max(0.0, (km - SIGMA_MULTIPLIER * sigma_km) * 1000),
        high_metres=(km + SIGMA_MULTIPLIER * sigma_km) * 1000,
        sigma_metres=sigma_km * 1000,
        extrapolated=not (lo_s <= duration_s <= hi_s),
    )


def _distance_confidence(kb: dict[str, Any], est: DistanceEstimate, obs: dict[str, Any]) -> tuple[float, list[str]]:
    f = kb["confidence_model"]["factors"]
    notes: list[str] = []

    value = f["r_squared"]["value"]

    runs = obs.get("n_waggle_runs_measured")
    protocol = f["protocol_factor"]["values"]
    if runs is None or runs >= 4:
        pf = protocol["runs_ge_4"]
    elif runs >= 2:
        pf = protocol["runs_2_or_3"]
        notes.append(f"измерено {runs} пробега вместо четырёх по протоколу источника")
    else:
        pf = protocol["runs_1"]
        notes.append("измерен один пробег: протокол источника требует усреднения по четырём")
    value *= pf

    if est.extrapolated:
        value *= f["range_factor"]["values"]["extrapolated"]
        notes.append("длительность вне откалиброванного диапазона 0.41–2.20 с: это экстраполяция")
    else:
        value *= f["range_factor"]["values"]["within_calibrated_range"]

    if obs.get("individual_calibration_known"):
        value *= f["calibration_factor"]["values"]["individual_calibration_known"]
    else:
        value *= f["calibration_factor"]["values"]["unknown"]
        notes.append("калибровка этой конкретной пчелы неизвестна")

    return min(value, kb["confidence_cap"]), notes


def _direction(kb: dict[str, Any], obs: dict[str, Any]) -> tuple[Step | None, Unknown | None, float | None]:
    direction = kb["quantitative_model"]["direction"]
    err = direction["angular_error_deg"]
    angle = obs.get("angle_from_vertical_deg")
    surface = obs.get("dance_surface", "vertical_comb")

    if surface == "horizontal":
        return None, Unknown(
            field_ru="Направление",
            kind=UnknownKind.NOT_APPLICABLE,
            explanation_ru=(
                "Танец на горизонтальной поверхности под открытым небом: пчела направляет пробег "
                "прямо на цель, гравитационного пересчёта нет. Угол от вертикали здесь не работает."
            ),
        ), None

    if angle is None:
        return None, Unknown(
            field_ru="Направление",
            kind=UnknownKind.DATA_GAP,
            explanation_ru="Не указан угол пробега от вертикали. Это пробел в наблюдении: измерьте угол — направление посчитается.",
        ), None

    sun = obs.get("sun_azimuth_deg")
    if sun is None:
        step = Step(
            label_ru="Направление (относительно солнца)",
            value_ru=f"{angle:.0f}° по часовой стрелке от азимута солнца, коридор ±{err}°",
            source_ids=[direction["source_id"], direction["angular_error_source_id"]],
        )
        unknown = Unknown(
            field_ru="Компасное направление",
            kind=UnknownKind.DATA_GAP,
            explanation_ru="Не указан азимут солнца, поэтому направление известно только относительно него, а не в компасных градусах.",
        )
        return step, unknown, kb["confidence_model"]["factors"]["direction_confidence"]["value"]

    bearing = (sun + angle) % 360
    step = Step(
        label_ru="Направление (компасное)",
        value_ru=(
            f"{bearing:.0f}° ({_compass_ru(bearing)}), коридор "
            f"{(bearing - err) % 360:.0f}–{(bearing + err) % 360:.0f}°"
        ),
        source_ids=[direction["source_id"], direction["angular_error_source_id"]],
    )
    return step, None, kb["confidence_model"]["factors"]["direction_confidence"]["value"]


def translate(observation: dict[str, Any]) -> Result:
    kb = load_species(SLUG)
    rules = {r["dance_type"]: r for r in kb["rules"]}
    dance_type = observation.get("dance_type")

    if dance_type not in rules:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Не указан тип танца — считать нечего.",
            unknowns=[
                Unknown(
                    field_ru="Тип танца",
                    kind=UnknownKind.DATA_GAP,
                    explanation_ru="Без типа танца непонятно, о чём вообще сигнал: о ресурсе, о нехватке приёмщиц или о запрете вербовать.",
                )
            ],
        )

    rule = rules[dance_type]

    # Дрожащий танец и стоп-сигнал: значение установлено экспериментально,
    # но количественной модели для них нет — числа не выдумываем.
    if dance_type in ("tremble", "stop_signal"):
        return Result(
            species=SLUG,
            verdict=Verdict.TRANSLATED,
            headline_ru=rule["translation_ru"],
            confidence=None,
            confidence_level_ru="высокая (качественная оценка)",
            steps=[
                Step(label_ru="Тип сигнала", value_ru=rule["detail_ru"], source_ids=rule["source_ids"]),
            ],
            unknowns=[
                Unknown(
                    field_ru="Вектор",
                    kind=UnknownKind.NOT_ENCODED,
                    explanation_ru="Этот сигнал не содержит направления и расстояния в принципе. Дополнительные измерения ничего не добавят.",
                )
            ],
            alternatives_ru=rule["alternatives_ru"],
            warnings_ru=[
                "Числовой уверенности нет: количественной модели для этого сигнала не опубликовано, "
                "а придумывать процент под требование интерфейса — ровно та подмена, которой приложение избегает."
            ],
            source_ids=rule["source_ids"],
        )

    if dance_type == "round":
        return Result(
            species=SLUG,
            verdict=Verdict.PARTIAL,
            headline_ru=rule["translation_ru"],
            confidence=None,
            confidence_level_ru="высокая (качественная оценка)",
            steps=[Step(label_ru="Тип сигнала", value_ru=rule["detail_ru"], source_ids=rule["source_ids"])],
            unknowns=[
                Unknown(
                    field_ru="Направление",
                    kind=UnknownKind.BEYOND_MODEL,
                    explanation_ru=(
                        "Направление в круговом танце есть, и пчёлы им пользуются, но виляющая фаза "
                        "здесь слишком коротка: модель расстояния откалибрована от 100 м и на эту "
                        "дистанцию не распространяется. Досняв наблюдение, направление не получить — "
                        "нужна другая модель."
                    ),
                )
            ],
            alternatives_ru=rule["alternatives_ru"],
            source_ids=rule["source_ids"],
        )

    # Виляющий танец: полное декодирование.
    duration = observation.get("waggle_run_duration_s")
    if duration is None:
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Виляющий танец распознан, но расстояние считать не из чего.",
            unknowns=[
                Unknown(
                    field_ru="Длительность виляющей фазы",
                    kind=UnknownKind.DATA_GAP,
                    explanation_ru="Расстояние кодируется именно длительностью пробега. Без неё уравнение не применить.",
                )
            ],
            alternatives_ru=rule["alternatives_ru"],
            source_ids=rule["source_ids"],
        )

    est = estimate_distance(kb, float(duration))
    if est is None:
        model = kb["quantitative_model"]["distance"]
        return Result(
            species=SLUG,
            verdict=Verdict.INSUFFICIENT,
            headline_ru="Длительность ниже свободного члена модели — расстояние получилось бы отрицательным.",
            warnings_ru=[
                f"Модель определена от {model['calibrated_range_duration_s'][0]} с. "
                f"Значение {duration} с лежит ниже физически осмысленного диапазона."
            ],
            source_ids=[model["source_id"]],
        )

    dist_conf, notes = _distance_confidence(kb, est, observation)
    dir_step, dir_unknown, dir_conf = _direction(kb, observation)

    model = kb["quantitative_model"]["distance"]
    steps = [
        Step(
            label_ru="Расстояние",
            value_ru=(
                f"{est.metres:.0f} м (интервал {est.low_metres:.0f}–{est.high_metres:.0f} м, ±2 SD). "
                f"Пробег {duration} с подставлен в обращённое уравнение сегментированной регрессии."
            ),
            source_ids=[model["source_id"]],
        )
    ]
    if dir_step:
        steps.append(dir_step)

    unknowns = [u for u in (dir_unknown,) if u]

    if dir_conf is None:
        confidence = dist_conf
        scope = "относится только к расстоянию: направление не посчитано"
    else:
        confidence = min(dist_conf, dir_conf)
        scope = "относится к вектору целиком: и к расстоянию, и к направлению"
    warnings = list(notes)
    if not observation.get("individual_calibration_known"):
        risk = model["individual_calibration_risk"]
        warnings.append(
            f"Отдельно от интервала: у каждой пчелы своя калибровка. Если она неизвестна, "
            f"систематическое смещение расстояния может достигать {risk['systematic_bias_fraction'] * 100:.0f}%. "
            f"Это не случайный разброс, поэтому в интервал выше не входит."
        )
    if dir_conf is not None:
        warnings.append(
            "Итоговая уверенность — верхняя граница: она не выше уверенности слабейшего из компонентов вектора."
        )
    if observation.get("dance_surface") == "swarm_surface":
        warnings.append(
            "Танец на поверхности роя: тот же механизм чаще рекламирует место для нового гнезда, а не корм."
        )

    verdict = Verdict.TRANSLATED if dir_step and not dir_unknown else Verdict.PARTIAL

    return Result(
        species=SLUG,
        verdict=verdict,
        headline_ru=rule["translation_ru"],
        confidence=confidence,
        confidence_level_ru=confidence_level_ru(confidence),
        confidence_scope_ru=scope,
        steps=steps,
        unknowns=unknowns,
        alternatives_ru=rule["alternatives_ru"],
        warnings_ru=warnings,
        source_ids=sorted({*rule["source_ids"], model["source_id"], "schurch2016"}),
    )
