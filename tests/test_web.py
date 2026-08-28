"""Тесты веб-слоя: разбор ввода и сборка страниц.

Сервер не поднимается, проверяются функции рендеринга и разбора.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from animal_translator import web  # noqa: E402
from animal_translator.forms import FieldError, filled_count, parse_observation  # noqa: E402
from animal_translator.knowledge import KNOWLEDGE_DIR, load_species  # noqa: E402

SLUGS = sorted(p.stem for p in KNOWLEDGE_DIR.glob("*.json"))


class TestObservationParsing(unittest.TestCase):
    def setUp(self):
        self.schema = load_species("honeybee")["input_schema"]

    def test_empty_field_stays_unfilled(self):
        obs = parse_observation(self.schema, {"dance_type": ["waggle"], "waggle_run_duration_s": [""]})
        self.assertEqual(obs, {"dance_type": "waggle"})

    def test_numbers_accept_comma_decimal_separator(self):
        obs = parse_observation(self.schema, {"waggle_run_duration_s": ["1,2"]})
        self.assertAlmostEqual(obs["waggle_run_duration_s"], 1.2)

    def test_integer_field_stays_integer(self):
        obs = parse_observation(self.schema, {"n_waggle_runs_measured": ["4"]})
        self.assertIsInstance(obs["n_waggle_runs_measured"], int)

    def test_boolean_has_three_states(self):
        schema = load_species("elephant")["input_schema"]
        self.assertTrue(parse_observation(schema, {"headshaking": ["yes"]})["headshaking"])
        self.assertFalse(parse_observation(schema, {"headshaking": ["no"]})["headshaking"])
        self.assertNotIn("headshaking", parse_observation(schema, {"headshaking": [""]}))

    def test_number_list_is_parsed(self):
        schema = load_species("spermwhale")["input_schema"]
        obs = parse_observation(schema, {"inter_click_intervals_s": ["0.12, 0.12; 0.35 0.12"]})
        self.assertEqual(obs["inter_click_intervals_s"], [0.12, 0.12, 0.35, 0.12])

    def test_garbage_in_a_number_field_is_reported_not_swallowed(self):
        with self.assertRaises(FieldError):
            parse_observation(self.schema, {"waggle_run_duration_s": ["абв"]})

    def test_filled_count_reflects_the_schema(self):
        obs = parse_observation(self.schema, {"dance_type": ["waggle"], "waggle_run_duration_s": ["1.2"]})
        self.assertEqual(filled_count(self.schema, obs), (2, len(self.schema)))


class TestPagesRender(unittest.TestCase):
    def test_index_lists_every_species(self):
        html = web.index_page().decode("utf-8")
        for slug in SLUGS:
            with self.subTest(slug):
                self.assertIn(load_species(slug)["name_ru"], html)

    def test_every_species_form_renders_all_its_fields(self):
        for slug in SLUGS:
            kb = load_species(slug)
            html = web.species_page(slug).decode("utf-8")
            for field in kb["input_schema"]:
                with self.subTest(slug=slug, field=field["id"]):
                    self.assertIn(f'name="{field["id"]}"', html)

    def test_every_knowledge_page_renders(self):
        for slug in SLUGS:
            kb = load_species(slug)
            html = web.knowledge_page(kb).decode("utf-8")
            with self.subTest(slug):
                for source in kb["sources"]:
                    self.assertIn(source["id"], html)
                for myth in kb["myths"]:
                    self.assertIn(myth["claim_ru"][:30], html)

    def test_result_shows_confidence_reasoning_and_sources(self):
        kb = load_species("honeybee")
        obs = {"dance_type": "waggle", "waggle_run_duration_s": 1.2,
               "angle_from_vertical_deg": 40, "sun_azimuth_deg": 180}
        html = web.render_result(kb, web._engine("honeybee").translate(obs), obs)
        self.assertIn("Почему такая трактовка", html)
        self.assertIn("Источники этого вывода", html)
        self.assertIn("doi.org/10.7717/peerj.11187", html)
        self.assertIn("636", html)

    def test_refusal_is_rendered_as_such(self):
        kb = load_species("spermwhale")
        obs = {"signal_type": "coda", "inter_click_intervals_s": [0.1, 0.1, 0.1]}
        html = web.render_result(kb, web._engine("spermwhale").translate(obs), obs)
        self.assertIn("перевода не существует", html)
        self.assertIn("в сигнале этого нет", html)

    def test_every_species_engine_is_importable_by_slug(self):
        for slug in SLUGS:
            with self.subTest(slug):
                self.assertTrue(hasattr(web._engine(slug), "translate"))


class TestEscaping(unittest.TestCase):
    def test_user_input_is_escaped_in_the_form(self):
        values = {"waggle_run_duration_s": ['"><script>alert(1)</script>']}
        html = web.species_page("honeybee", values).decode("utf-8")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_error_message_with_markup_is_escaped(self):
        values = {"waggle_run_duration_s": ["<b>x</b>"]}
        page = web.species_page("honeybee", values).decode("utf-8")
        self.assertNotIn("<b>x</b>", page)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestIllustrations(unittest.TestCase):
    def test_every_species_has_an_illustration_and_palette(self):
        from animal_translator.illustrations import accent, svg

        for slug in SLUGS:
            with self.subTest(slug):
                mark = svg(slug)
                self.assertTrue(mark.startswith("<svg"))
                self.assertTrue(mark.endswith("</svg>"))
                self.assertIn("viewBox", mark)
                palette = accent(slug)
                for key in ("ink", "wash", "line"):
                    self.assertRegex(palette[key], r"^#[0-9a-f]{6}$")

    def test_species_accents_are_distinct(self):
        from animal_translator.illustrations import accent

        inks = [accent(slug)["ink"] for slug in SLUGS]
        self.assertEqual(len(inks), len(set(inks)))

    def test_pages_load_no_external_resources(self):
        """Страница должна открываться без сети: сторонних ресурсов она не подгружает."""
        import re

        loaders = re.compile(
            r"""<img[^>]+src=|<script[^>]+src=|<link[^>]+rel=["']stylesheet|@import|url\(\s*['"]?https?:""",
            re.I,
        )
        pages = [("index", web.index_page())]
        pages += [(s, web.species_page(s)) for s in SLUGS]
        pages += [(f"{s}/kb", web.knowledge_page(load_species(s))) for s in SLUGS]

        for name, payload in pages:
            with self.subTest(name):
                self.assertIsNone(loaders.search(payload.decode("utf-8")))

    def test_outbound_links_point_only_to_declared_sources(self):
        """Единственные внешние адреса на страницах — ссылки из базы знаний."""
        import re
        from urllib.parse import urlparse

        from animal_translator.illustrations import credit

        allowed = {"doi.org", "www.w3.org"}
        for slug in SLUGS:
            info = credit(slug)
            if info:
                allowed.add(urlparse(info["page"]).netloc)
                allowed.add(urlparse(info["licence_url"]).netloc)
            for source in load_species(slug)["sources"]:
                for link in (source.get("url"), (source.get("correction") or {}).get("url")):
                    if link:
                        allowed.add(urlparse(link).netloc)
                oa = source.get("open_access") or {}
                if oa.get("kind") == "url":
                    allowed.add(urlparse(oa["url"]).netloc)
                elif oa.get("kind") == "pmc":
                    allowed.add("pmc.ncbi.nlm.nih.gov")

        pages = [web.index_page()] + [web.species_page(s) for s in SLUGS]
        pages += [web.knowledge_page(load_species(s)) for s in SLUGS]
        for payload in pages:
            for url in re.findall(r'https?://[^"\s<>]+', payload.decode("utf-8")):
                with self.subTest(url=url):
                    self.assertIn(urlparse(url).netloc, allowed)


class TestIllustrationCredits(unittest.TestCase):
    """Силуэты взяты из внешнего источника, поэтому авторство обязано быть указано."""

    def test_every_illustration_declares_licence_and_origin(self):
        from animal_translator.illustrations import credit

        for slug in SLUGS:
            with self.subTest(slug):
                info = credit(slug)
                self.assertIsNotNone(info, f"{slug}: нет сведений о происхождении силуэта")
                for key in ("subject", "licence", "licence_url", "source", "page", "author"):
                    self.assertTrue(info.get(key))

    def test_attribution_appears_on_every_page(self):
        """CC BY требует указания авторства; оно вынесено в подвал, но должно быть везде."""
        from animal_translator.illustrations import credit

        authors = {credit(s)["author"] for s in SLUGS}
        pages = [web.index_page()] + [web.species_page(s) for s in SLUGS]
        pages += [web.knowledge_page(load_species(s)) for s in SLUGS]
        for payload in pages:
            html = payload.decode("utf-8")
            with self.subTest(page=html[:60]):
                self.assertIn("game-icons.net", html)
                self.assertIn("CC BY 3.0", html)
                for author in authors:
                    self.assertIn(author, html)

    def test_attribution_is_not_repeated_in_the_hero(self):
        """В шапке вида подпись не нужна: она мешает названию и дублируется на каждой странице."""
        html = web.species_page("dog").decode("utf-8")
        hero = html.split('class="hero"')[1].split("</div></div>")[0]
        self.assertNotIn("game-icons", hero)

    def test_pictograms_do_not_claim_to_depict_a_species(self):
        """Пиктограмма обобщённая, и это должно быть записано, а не подразумеваться."""
        from animal_translator.illustrations import credit

        for slug in SLUGS:
            with self.subTest(slug):
                self.assertIn("Обобщённая пиктограмма", credit(slug)["note_ru"])

    def test_credit_line_does_not_mention_a_latin_name(self):
        """Подпись не должна создавать впечатление, что изображён конкретный вид."""
        import re

        from animal_translator.illustrations import credit_line

        for slug in SLUGS:
            with self.subTest(slug):
                self.assertIsNone(re.search(r"[A-Z][a-z]+ [a-z]+", credit_line(slug)))


class TestOpenAccessLinks(unittest.TestCase):
    """У источника со свободным полным текстом должна быть отдельная ссылка на него."""

    def test_open_access_field_is_structured(self):
        for slug in SLUGS:
            for source in load_species(slug)["sources"]:
                oa = source.get("open_access")
                with self.subTest(slug=slug, source=source["id"]):
                    if oa is None:
                        continue
                    self.assertIn(oa["kind"], ("pmc", "url", "publisher"))
                    if oa["kind"] == "pmc":
                        self.assertRegex(oa["id"], r"^PMC\d+$")
                    elif oa["kind"] == "url":
                        self.assertTrue(oa["url"].startswith("https://"))
                        self.assertTrue(oa.get("note_ru"))
                    else:
                        self.assertTrue(oa.get("note_ru"))

    def test_pmc_sources_get_a_direct_link(self):
        html = web.knowledge_page(load_species("honeybee")).decode("utf-8")
        self.assertIn("pmc.ncbi.nlm.nih.gov/articles/PMC8029670/", html)
        self.assertIn("открытый текст", html)

    def test_paywalled_sources_say_so(self):
        html = web.knowledge_page(load_species("honeybee")).decode("utf-8")
        self.assertIn("полный текст закрыт", html)

    def test_result_page_also_shows_access_status(self):
        kb = load_species("honeybee")
        obs = {"dance_type": "waggle", "waggle_run_duration_s": 1.2}
        html = web.render_result(kb, web._engine("honeybee").translate(obs), obs)
        self.assertRegex(html, r"открытый текст|полный текст закрыт")


class TestKnowledgePageNavigation(unittest.TestCase):
    def test_knowledge_page_says_where_you_are(self):
        for slug in SLUGS:
            html = web.knowledge_page(load_species(slug)).decode("utf-8")
            with self.subTest(slug):
                self.assertIn("База знаний, методика и мифы", html)

    def test_knowledge_page_links_back_to_the_species(self):
        for slug in SLUGS:
            html = web.knowledge_page(load_species(slug)).decode("utf-8")
            with self.subTest(slug):
                self.assertIn(f'class="back" href="/species/{slug}"', html)


class TestMethodologyIsShown(unittest.TestCase):
    """Страница называется «база знаний, методика и мифы» — методика должна быть."""

    def test_every_species_has_a_methodology_section(self):
        for slug in SLUGS:
            html = web.knowledge_page(load_species(slug)).decode("utf-8")
            with self.subTest(slug):
                self.assertIn("Методика", html)

    def test_dog_reliability_numbers_reach_the_page(self):
        import html as html_mod

        kb = load_species("dog")
        html = web.knowledge_page(kb).decode("utf-8")
        rel = kb["reliability"]
        self.assertIn(f'{rel["overall_accuracy"]:.0%}', html)
        self.assertIn(f'{rel["random_baseline"]:.0%}', html)
        import html as html_mod

        for ctx, stats in rel["per_context"].items():
            with self.subTest(ctx):
                self.assertIn(html_mod.escape(stats["p_ru"]), html)

    def test_bee_equations_reach_the_page(self):
        kb = load_species("honeybee")
        html = web.knowledge_page(kb).decode("utf-8")
        near, _ = kb["quantitative_model"]["distance"]["forward_equations"]
        self.assertIn(str(near["intercept_s"]), html)
        self.assertIn(str(near["slope_s_per_km"]), html)
        self.assertIn(kb["quantitative_model"]["distance"]["subspecies"], html)

    def test_sample_size_of_each_source_is_shown(self):
        for slug in SLUGS:
            kb = load_species(slug)
            html = web.knowledge_page(kb).decode("utf-8")
            for source in kb["sources"]:
                with self.subTest(slug=slug, source=source["id"]):
                    import html as html_mod

                    self.assertIn(html_mod.escape(source["sample_ru"][:40]), html)
