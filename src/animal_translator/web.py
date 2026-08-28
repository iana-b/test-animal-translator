"""Веб-интерфейс на стандартной библиотеке.

Страницы:
  /                      выбор вида
  /species/<slug>        форма наблюдения и результат разбора
  /species/<slug>/kb     база знаний вида: источники, методика, мифы
"""

from __future__ import annotations

import html
import importlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .forms import BOOL_CHOICES, FieldError, filled_count, parse_observation
from .illustrations import accent, credit, credit_line, svg
from .knowledge import KNOWLEDGE_DIR, load_species
from .result import Result, UnknownKind, Verdict

SPECIES_ORDER = ["honeybee", "dog", "elephant", "spermwhale"]

VERDICT_RU = {
    Verdict.TRANSLATED: "трактовка выдана",
    Verdict.PARTIAL: "трактовка неполная",
    Verdict.INSUFFICIENT: "данных недостаточно",
    Verdict.NO_TRANSLATION_EXISTS: "перевода не существует",
}

UNKNOWN_RU = {
    UnknownKind.DATA_GAP: "пробел в наблюдении",
    UnknownKind.NOT_ENCODED: "в сигнале этого нет",
    UnknownKind.NOT_APPLICABLE: "правило здесь не работает",
    UnknownKind.BEYOND_MODEL: "за пределами модели",
}

CSS = """
:root { --ink:#1a1a18; --dim:#5c5c55; --line:#d6d4cb; --paper:#f7f6f1; --panel:#fff;
        --mark:#2f5d50; --wash:#eef2ef; --edge:#d6d4cb; --warn:#8a5a2b;
        --fs:18px; --lh:1.62; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
       font:var(--fs)/var(--lh) "Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
       -webkit-text-size-adjust:100%; }
code, .num { font-family:"SFMono-Regular",Menlo,Consolas,monospace; font-variant-numeric:tabular-nums; }
a { color:var(--mark); text-underline-offset:2px; }

.wrap { max-width:1180px; margin:0 auto; padding:32px 24px 80px; }
header { border-bottom:3px solid var(--mark); padding-bottom:18px; margin-bottom:30px; }
header h1 { margin:0 0 8px; font-size:27px; line-height:1.25; letter-spacing:.005em; }
header p { margin:0; color:var(--dim); font-size:16.5px; max-width:74ch; }
nav { margin-top:20px; display:flex; flex-wrap:wrap; gap:8px; }
nav a { display:inline-block; padding:9px 16px; border:1px solid var(--line); background:var(--panel);
        text-decoration:none; color:var(--ink); font-size:16.5px; }
nav a.on { border-color:var(--mark); color:#fff; background:var(--mark); }
nav a:hover { border-color:var(--mark); }

.hero { display:flex; align-items:center; gap:26px; background:var(--wash);
        border:1px solid var(--edge); border-left:6px solid var(--mark);
        padding:20px 26px; margin-bottom:26px; }
.hero .art { color:var(--mark); width:120px; flex:0 0 120px; }
.hero .art svg { display:block; width:100%; height:auto; }
.hero h2 { margin:0 0 5px; font-size:30px; line-height:1.2; color:var(--mark); }
.hero i { color:var(--dim); font-size:16.5px; }
footer { margin-top:56px; padding-top:20px; border-top:1px solid var(--line);
         font-size:14.5px; color:var(--dim); }
footer a { color:var(--dim); }
.hero .label { display:inline-block; font-size:12.5px; text-transform:uppercase;
               letter-spacing:.09em; color:#fff; background:var(--mark);
               padding:4px 11px; margin-bottom:9px; }
.back { display:inline-block; margin-bottom:16px; font-size:16.5px; text-decoration:none; }
.back:hover { text-decoration:underline; }

.cols { display:grid; grid-template-columns:minmax(300px,400px) 1fr; gap:30px; align-items:start; }
@media (max-width:900px){ .cols { grid-template-columns:1fr; } .hero .art { width:92px; flex:0 0 92px; } }

.panel { background:var(--panel); border:1px solid var(--line); padding:26px; }
.panel h2 { margin:0 0 20px; font-size:15px; text-transform:uppercase; letter-spacing:.09em;
            color:var(--mark); }
.panel p { max-width:72ch; }

label { display:block; margin-bottom:20px; font-size:16.5px; }
label span.q { display:block; margin-bottom:6px; font-weight:600; }
label small { display:block; color:var(--dim); font-size:14.5px; margin-top:6px; line-height:1.5; }
select, input[type=text] { width:100%; padding:11px 12px; border:1px solid var(--line);
       background:var(--paper); color:var(--ink);
       font-family:inherit; font-size:17px; line-height:1.4; }
select:focus, input[type=text]:focus { outline:2px solid var(--mark); outline-offset:-1px; }
::placeholder { color:#9a9890; opacity:1; }
button { padding:13px 26px; border:1px solid var(--mark); background:var(--mark); color:#fff;
         font-family:inherit; font-size:18px; cursor:pointer; }
button:hover { filter:brightness(1.12); }

.verdict { display:inline-block; font-size:13px; text-transform:uppercase; letter-spacing:.09em;
           color:#fff; background:var(--mark); padding:5px 13px; }
.headline { font-size:25px; line-height:1.35; margin:14px 0 18px; max-width:44ch; }
.conf { border-top:1px solid var(--line); border-bottom:1px solid var(--line);
        padding:18px 0; margin:20px 0; }
.conf .big { font-size:44px; line-height:1; color:var(--mark); }
.conf .scope { color:var(--dim); font-size:15px; margin-top:6px; }
.bar { height:7px; background:var(--line); margin-top:14px; }
.bar i { display:block; height:7px; background:var(--mark); }

h3.sec { font-size:14px; text-transform:uppercase; letter-spacing:.09em; color:var(--mark);
         margin:30px 0 14px; border-top:1px solid var(--line); padding-top:20px; }
.step { margin-bottom:15px; max-width:78ch; }
.step b { font-weight:600; }
.tag { display:inline-block; font-size:12.5px; text-transform:uppercase; letter-spacing:.07em;
       border:1px solid var(--line); padding:2px 8px; color:var(--dim); margin-right:7px;
       white-space:nowrap; }
.tag.ref { text-transform:none; letter-spacing:0; font-family:"SFMono-Regular",Menlo,Consolas,monospace; }
.unk { border-left:4px solid var(--edge); padding:4px 0 4px 16px; margin-bottom:16px; max-width:78ch; }
.unk b { display:inline-block; margin-top:5px; }
.warn { border-left:4px solid var(--warn); padding:4px 0 4px 16px; margin-bottom:14px;
        color:#3f3f3a; font-size:16.5px; max-width:78ch; }

ul.src { list-style:none; padding:0; margin:0; font-size:16px; }
ul.src li { margin-bottom:18px; padding-bottom:18px; border-bottom:1px solid var(--line);
            max-width:82ch; line-height:1.55; }
ul.src li:last-child { border-bottom:0; }
.grade { font-size:14.5px; color:var(--dim); }
.grade a { color:var(--dim); }
.myth { margin-bottom:22px; max-width:80ch; }
.myth b { color:var(--warn); }
.err { border-left:4px solid var(--warn); padding-left:16px; font-size:17px; }

.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:20px; }
.card { display:block; text-decoration:none; color:inherit; background:var(--wash);
        border:1px solid var(--edge); border-top:5px solid var(--mark); padding:22px; }
.card:hover { background:var(--panel); }
.card .art { color:var(--mark); height:96px; margin-bottom:14px; }
.card .art svg { height:96px; width:auto; display:block; margin:0 auto; }
.card b { display:block; font-size:21px; margin-bottom:5px; color:var(--mark); }
.card i { display:block; font-style:italic; color:var(--dim); font-size:15px; margin-bottom:12px; }
.card span { font-size:16px; color:#3f3f3a; line-height:1.5; }
"""


def e(text: Any) -> str:
    return html.escape(str(text))


def _species_list() -> list[dict[str, Any]]:
    slugs = [p.stem for p in KNOWLEDGE_DIR.glob("*.json")]
    slugs.sort(key=lambda s: SPECIES_ORDER.index(s) if s in SPECIES_ORDER else 99)
    return [load_species(s) for s in slugs]


def _engine(slug: str):
    return importlib.import_module(f".species.{slug}", package=__package__)


def page(title: str, body: str, active: str = "") -> bytes:
    a = accent(active)
    palette = (f":root{{--mark:{a['ink']};--wash:{a['wash']};--edge:{a['line']};}}" if active else "")
    nav = "".join(
        f'<a class="{"on" if kb["slug"] == active else ""}" href="/species/{kb["slug"]}">{e(kb["name_ru"])}</a>'
        for kb in _species_list()
    )
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}{palette}</style></head><body><div class="wrap">
<header><h1><a href="/" style="text-decoration:none;color:inherit">Переводчик сигналов животных</a></h1>
<p>Трактовки строятся на опубликованных исследованиях. Каждое число возводится к источнику,
и приложение отказывается отвечать там, где данных нет.</p>
<nav>{nav}</nav></header>{body}{_footer()}</div></body></html>""".encode("utf-8")


def index_page() -> bytes:
    cards = "".join(
        f'<a class="card" href="/species/{kb["slug"]}" style="--mark:{accent(kb["slug"])["ink"]};'
        f'--wash:{accent(kb["slug"])["wash"]};--edge:{accent(kb["slug"])["line"]}">'
        f'<div class="art">{svg(kb["slug"])}</div><b>{e(kb["name_ru"])}</b>'
        f'<i>{e(kb["scientific_name"])}</i><span>{e(kb["engine_note_ru"][:150])}…</span></a>'
        for kb in _species_list()
    )
    return page("Переводчик сигналов животных", f'<div class="cards">{cards}</div>')


def render_form(kb: dict[str, Any], values: dict[str, list[str]]) -> str:
    rows = []
    for field in kb["input_schema"]:
        current = (values.get(field["id"], [""])[0] or "")
        hint = f'<small>{e(field["hint_ru"])}</small>' if field.get("hint_ru") else ""
        req = " *" if field.get("required") else ""

        if field["type"] == "boolean":
            options = BOOL_CHOICES
        elif field["type"] == "choice":
            options = [("", "не указано")] + [(o["value"], o["label_ru"]) for o in field["options"]]
        else:
            example = f' placeholder="{e(field["example_ru"])}"' if field.get("example_ru") else ""
            rows.append(
                f'<label><span class="q">{e(field["label_ru"])}{req}</span>'
                f'<input type="text" name="{e(field["id"])}" value="{e(current)}"{example}>{hint}</label>'
            )
            continue

        opts = "".join(
            f'<option value="{e(v)}"{" selected" if v == current else ""}>{e(t)}</option>'
            for v, t in options
        )
        rows.append(
            f'<label><span class="q">{e(field["label_ru"])}{req}</span>'
            f'<select name="{e(field["id"])}">{opts}</select>{hint}</label>'
        )

    return (
        f'<form method="get" class="panel"><h2>Наблюдение</h2>{"".join(rows)}'
        f'<button type="submit">Разобрать сигнал</button></form>'
    )


def render_result(kb: dict[str, Any], res: Result, observation: dict[str, Any]) -> str:
    sources = {s["id"]: s for s in kb["sources"]}
    out = [f'<div class="panel"><div class="verdict">{e(VERDICT_RU[res.verdict])}</div>',
           f'<div class="headline">{e(res.headline_ru)}</div>']

    if res.confidence is not None:
        pct = round(res.confidence * 100)
        out.append(
            f'<div class="conf"><span class="big num">{pct}%</span> '
            f'<span class="scope">— {e(res.confidence_level_ru or "")}</span>'
            + (f'<div class="scope">{e(res.confidence_scope_ru)}</div>' if res.confidence_scope_ru else "")
            + f'<div class="bar"><i style="width:{pct}%"></i></div></div>'
        )
    elif res.confidence_level_ru:
        out.append(f'<div class="conf"><b>{e(res.confidence_level_ru)}</b>'
                   + (f'<div class="scope">{e(res.confidence_scope_ru)}</div>' if res.confidence_scope_ru else "")
                   + '<div class="scope">Числовая оценка для этого случая не выводится.</div></div>')

    filled, total = filled_count(kb["input_schema"], observation)
    out.append(f'<div class="scope">Заполнено полей: <span class="num">{filled}</span> из '
               f'<span class="num">{total}</span></div>')

    if res.steps:
        out.append('<h3 class="sec">Почему такая трактовка</h3>')
        for s in res.steps:
            refs = " ".join(f'<span class="tag ref">{e(sid)}</span>' for sid in s.source_ids)
            out.append(f'<div class="step"><b>{e(s.label_ru)}:</b> {e(s.value_ru)} {refs}</div>')

    if res.unknowns:
        out.append('<h3 class="sec">Что осталось неизвестным</h3>')
        for u in res.unknowns:
            out.append(f'<div class="unk"><span class="tag">{e(UNKNOWN_RU[u.kind])}</span>'
                       f'<b>{e(u.field_ru)}</b><br>{e(u.explanation_ru)}</div>')

    if res.alternatives_ru:
        out.append('<h3 class="sec">Альтернативные трактовки</h3><div>'
                   + "".join(f'<div class="step">{e(a)}</div>' for a in res.alternatives_ru) + "</div>")

    if res.warnings_ru:
        out.append('<h3 class="sec">Оговорки</h3>')
        out.extend(f'<div class="warn">{e(w)}</div>' for w in res.warnings_ru)

    used = [sources[i] for i in dict.fromkeys(res.source_ids) if i in sources]
    if used:
        out.append('<h3 class="sec">Источники этого вывода</h3><ul class="src">')
        for s in used:
            link, label = _link_label(s)
            out.append(f'<li>{e(s["authors"])} ({s["year"]}). {e(s["title"])}. <i>{e(s["journal"])}</i>. '
                       + (f'<a href="{e(link)}" target="_blank" rel="noopener">{e(label)}</a>' if link else "")
                       + _oa_fragment(s)
                       + f'<br><span class="grade">доказательность: {e(s["evidence_grade"])}</span></li>')
        out.append("</ul>")

    out.append(f'<h3 class="sec">Ещё по виду</h3><a href="/species/{kb["slug"]}/kb">'
               'База знаний, методика и мифы →</a></div>')
    return "".join(out)


def _open_access(source: dict[str, Any]) -> tuple[str, str]:
    """Возвращает адрес свободного полного текста и подпись, если он есть."""
    info = source.get("open_access")
    if not info:
        return "", ""
    if info["kind"] == "pmc":
        return f'https://pmc.ncbi.nlm.nih.gov/articles/{info["id"]}/', f'открытый текст: {info["id"]}'
    if info["kind"] == "url":
        return info["url"], f'открытый текст: {info["note_ru"]}'
    return "", info["note_ru"]


def _link_label(source: dict[str, Any]) -> tuple[str, str]:
    """Возвращает адрес источника и подпись к нему."""
    if source.get("doi"):
        return f'https://doi.org/{source["doi"]}', f'doi.org/{source["doi"]}'
    url = source.get("url") or ""
    if not url:
        return "", ""
    label = urlparse(url).netloc.removeprefix("www.")
    return url, label


def _oa_fragment(source: dict[str, Any]) -> str:
    link, label = _open_access(source)
    if link:
        return f' · <a href="{e(link)}" target="_blank" rel="noopener">{e(label)}</a>'
    if label:
        return f' · <span class="grade">{e(label)}</span>'
    return ' · <span class="grade">полный текст закрыт</span>'


def _hero(slug: str, kb: dict[str, Any], label: str = "") -> str:
    tag = f'<span class="label">{e(label)}</span><br>' if label else ''
    return (f'<div class="hero"><div class="art">{svg(slug)}</div>'
            f'<div>{tag}<h2>{e(kb["name_ru"])}</h2>'
            f'<i>{e(kb["scientific_name"])}</i></div></div>')


def _footer() -> str:
    """Указание авторства пиктограмм: требование CC BY, выполняется разделом на сайте."""
    by_author: dict[str, dict[str, Any]] = {}
    for kb in _species_list():
        info = credit(kb["slug"])
        if info:
            by_author.setdefault(info["author"], info)
    if not by_author:
        return ""
    names = ", ".join(sorted(by_author))
    any_info = next(iter(by_author.values()))
    return (f'<footer>Пиктограммы видов: {e(names)} — '
            f'<a href="https://game-icons.net" target="_blank" rel="noopener">{e(any_info["source"])}</a>, '
            f'{e(any_info["licence"])}. Обобщённые пиктограммы, а не изображения конкретных видов.'
            f'</footer>')


def knowledge_page(kb: dict[str, Any]) -> bytes:
    out = [f'<div class="panel"><h2>Как устроен разбор</h2><p>{e(kb["engine_note_ru"])}</p>'
           f'<p class="scope">Движок: <code>{e(kb["engine"])}</code>. '
           f'Зрелость исследований: {e(kb.get("research_maturity_ru", "—"))}</p></div>']

    out.append('<div class="panel" style="margin-top:20px"><h2>Мифы</h2>')
    for m in kb["myths"]:
        refs = " ".join(f'<span class="tag ref">{e(i)}</span>' for i in m["source_ids"])
        out.append(f'<div class="myth" style="margin-bottom:15px"><b>Неверно:</b> {e(m["claim_ru"])}<br>'
                   f'<b style="color:var(--mark)">На деле:</b> {e(m["reality_ru"])} {refs}</div>')
    out.append("</div>")

    out.append('<div class="panel" style="margin-top:20px"><h2>Источники</h2><ul class="src">')
    for s in kb["sources"]:
        link, label = _link_label(s)
        extra = ""
        if s.get("correction"):
            correction_link, correction_label = _link_label(s["correction"])
            extra = (f'<br><span class="grade" style="color:var(--warn)">опубликована поправка: '
                     f'<a href="{e(correction_link)}" target="_blank" rel="noopener">'
                     f'{e(correction_label)}</a> — {e(s["correction"]["what_ru"])}</span>')
        out.append(
            f'<li><span class="tag ref">{e(s["id"])}</span>{e(s["authors"])} ({s["year"]}). {e(s["title"])}. '
            f'<i>{e(s["journal"])}</i>. '
            + (f'<a href="{e(link)}" target="_blank" rel="noopener">{e(label)}</a>' if link else "")
            + _oa_fragment(s)
            + f'<br><span class="grade">доказательность: {e(s["evidence_grade"])} · '
              f'лицензия: {e(s["licence"])}</span><br>{e(s["gives_ru"])}{extra}</li>'
        )
    out.append("</ul></div>")
    back = (f'<a class="back" href="/species/{kb["slug"]}">← Вернуться к разбору сигнала</a>')
    hero = _hero(kb["slug"], kb, "База знаний, методика и мифы")
    return page(f'{kb["name_ru"]} — база знаний', back + hero + "".join(out), kb["slug"])


def species_page(slug: str, values: dict[str, list[str]] | None = None,
                 result_html: str = "") -> bytes:
    kb = load_species(slug)
    body = (_hero(slug, kb) + f'<div class="cols">{render_form(kb, values or {})}'
            f'<div>{result_html or _placeholder(kb)}</div></div>')
    return page(kb["name_ru"], body, slug)


def _placeholder(kb: dict[str, Any]) -> str:
    return (f'<div class="panel"><h2>Результат</h2><p>{e(kb["engine_note_ru"])}</p>'
            f'<p class="scope">Заполните форму слева. Незаполненные поля снижают уверенность '
            f'или приводят к отказу от ответа.</p>'
            f'<p><a href="/species/{kb["slug"]}/kb">База знаний, методика и мифы →</a></p></div>')


class Handler(BaseHTTPRequestHandler):
    server_version = "AnimalTranslator/1.0"

    def log_message(self, *args):
        """Отключает журнал запросов в консоли."""
        pass

    def _send(self, payload: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _route(self) -> tuple[str, str]:
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if not parts:
            return "index", ""
        if parts[0] == "species" and len(parts) >= 2:
            return ("kb" if len(parts) > 2 and parts[2] == "kb" else "species"), parts[1]
        return "404", ""

    def do_GET(self) -> None:
        route, slug = self._route()
        known = {p.stem for p in KNOWLEDGE_DIR.glob("*.json")}
        if route == "index":
            return self._send(index_page())
        if slug not in known:
            return self._send(page("Не найдено", '<div class="panel">Такой страницы нет.</div>'), 404)
        if route == "kb":
            return self._send(knowledge_page(load_species(slug)))

        # Разбор доступен и по GET, поэтому у результата есть собственный адрес.
        values = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        if any(v and v[0] for v in values.values()):
            return self._send(self._render_species(slug, values))
        return self._send(species_page(slug))

    def _render_species(self, slug: str, values: dict[str, list[str]]) -> bytes:
        kb = load_species(slug)
        try:
            observation = parse_observation(kb["input_schema"], values)
        except FieldError as exc:
            return species_page(
                slug, values,
                f'<div class="panel"><h2>Ввод не разобран</h2><div class="err">{e(exc)}</div></div>')
        result = _engine(slug).translate(observation)
        return species_page(slug, values, render_result(kb, result, observation))

    def do_POST(self) -> None:
        route, slug = self._route()
        known = {p.stem for p in KNOWLEDGE_DIR.glob("*.json")}
        if route != "species" or slug not in known:
            return self._send(page("Не найдено", '<div class="panel">Такой страницы нет.</div>'), 404)

        length = int(self.headers.get("Content-Length") or 0)
        values = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        return self._send(self._render_species(slug, values))


def serve(port: int = 8000, host: str = "127.0.0.1") -> None:
    httpd = HTTPServer((host, port), Handler)
    print(f"Открой http://127.0.0.1:{port}  (Ctrl+C — остановить)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено.")
