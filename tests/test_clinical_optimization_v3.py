"""Regression tests for clinical negation filtering, compound safety (十八反/十九畏), tongue weights & UI upgrades."""

from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from app.acupuncture_diagnose import diagnose_symptoms
from app.formula_diagnose import diagnose_formulas
from app.main import app
from app.syndrome_composer import PATTERN_ATOMS, compose_differentiation
from app.syndrome_rules import are_formulas_redundant_siblings, detect_compound_herb_conflicts
from retrieval.tcm_synonyms import strip_clinical_negations


ROOT = Path(__file__).resolve().parents[1]


class ClinicalOptimizationV3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_clinical_negation_stripping_across_engines(self) -> None:
        pos, neg = strip_clinical_negations("未怀孕，不在经期，未做心脏手术，无发热，不恶心，无汗，口不渴，身反不恶寒")
        self.assertEqual(set(neg), {"怀孕", "经期", "心脏手术", "发热", "恶心"})
        self.assertIn("无汗", pos)
        self.assertIn("口不渴", pos)
        self.assertIn("身反不恶寒", pos)

        res_no_preg = compose_differentiation("未怀孕 咳嗽 恶寒 发热")
        self.assertNotIn("妊娠禁忌", res_no_preg["recognized_symptoms"])
        self.assertIn("怀孕", res_no_preg["recognized_negations"])
        self.assertNotIn("redline:pregnancy-contraindication", {r["id"] for r in res_no_preg["classical_redlines"]})

        res_no_period = compose_differentiation("不在经期 发热 恶寒 往来寒热")
        self.assertNotIn("经期热入血室", res_no_period["recognized_symptoms"])
        self.assertNotIn("redline:jingqi-chaihu", {r["id"] for r in res_no_period["classical_redlines"]})

        res_no_heart = compose_differentiation("未做心脏手术 心悸 喘 无汗 恶寒", "浮 紧")
        self.assertNotIn("心脏术后禁忌", res_no_heart["recognized_symptoms"])
        self.assertIn("麻黄汤", {c["name"] for c in res_no_heart["candidate_formulas"][:4]})

        # Acupuncture diagnose score must not inflate on negated tokens
        base_sc = diagnose_symptoms("头痛")["matched_patterns"][0]["score"]
        self.assertEqual(diagnose_symptoms("无发热 头痛")["matched_patterns"][0]["score"], base_sc)
        self.assertEqual(diagnose_symptoms("不恶心 头痛")["matched_patterns"][0]["score"], base_sc)

        # Stage 4 formula diagnose strips negated redline history
        f_res = diagnose_formulas("未怀孕 麻黄汤 恶寒 无汗")
        self.assertTrue(f_res["matched_formulas"])

    def test_single_hero_and_shibafan_and_sibling_guards(self) -> None:
        # Pure Taiyang exterior cold: Mahuang Tang covers 100%, should NOT auto-pair Mahuang-Fuzi-Xixin
        mht = compose_differentiation("发热 恶寒 头痛 无汗", "浮 紧")
        top_reg = mht["compound_regimens"][0]
        self.assertFalse(top_reg["is_compound"])
        self.assertEqual(top_reg["formula_names"], ["麻黄汤"])
        self.assertFalse(any("生附子" in line for line in mht["decoction_and_safety"]))

        # 十八反: 十枣汤 (甘遂/大戟/芫花) + 炙甘草汤 (甘草) must NEVER co-compound
        shizao = compose_differentiation("悬饮 胁痛 咳唾引痛 心悸", "沉 弦 结代")
        for reg in shizao["compound_regimens"]:
            fnames = set(reg["formula_names"])
            self.assertFalse({"十枣汤", "炙甘草汤"}.issubset(fnames))
        self.assertTrue(any("十八反" in line for line in shizao["decoction_and_safety"]))

        # 十八反: 附子 + 半夏 cross-formula compounding must be blocked cleanly
        conflict = detect_compound_herb_conflicts(["附子", "桂枝", "芍药"], ["半夏", "黄芩", "干姜"], "桂枝芍药知母汤", "半夏泻心汤")
        self.assertTrue(conflict["blocking"])
        lijie = compose_differentiation("历节疼痛 关节屈伸不利 寒湿痹痛 呕吐 心下痞")
        for reg in lijie["compound_regimens"]:
            fnames = set(reg["formula_names"])
            self.assertFalse({"桂枝芍药知母汤", "半夏泻心汤"}.issubset(fnames))

        # Sibling & cross-book guards
        self.assertTrue(are_formulas_redundant_siblings("jinkui:射干麻黄汤", "shanghan:小青龙汤"))
        self.assertTrue(are_formulas_redundant_siblings("shanghan:真武汤", "shanghan:附子汤"))
        self.assertTrue(are_formulas_redundant_siblings("jinkui:苓桂术甘汤", "shanghan:茯苓桂枝白术甘草汤"))
        self.assertTrue(are_formulas_redundant_siblings("shanghan:炙甘草汤", "jinkui:灸甘草汤"))

    def test_tongue_weights_missing_atoms_and_clue_dedup(self) -> None:
        self.assertGreaterEqual(len(PATTERN_ATOMS), 240)
        tongue_res = compose_differentiation("心烦 失眠 舌红少苔", "细 数")
        self.assertIn("舌红少苔", tongue_res["candidate_formulas"][0].get("matched_tongues", []))

        # Missing internal Jingfang formulas now resolvable
        for q, expected in [
            ("阴狐疝 偏大", "蜘蛛散"),
            ("气利 矢气频", "诃黎勒散"),
            ("水肿 身冷 无汗", "麻黄附子汤"),
            ("蛔虫 腹痛 吐涎", "甘草粉蜜汤"),
        ]:
            out = compose_differentiation(q)
            self.assertEqual(out["candidate_formulas"][0]["name"], expected, f"Expected {expected} for {q}")

        # Cross-book duplicate clues deduplicated (e.g., 吴茱萸汤 should appear only once in matched_jingfang_clues)
        mig = compose_differentiation("偏头痛 呕吐", "弦 细")
        wu_hits = [c for c in mig["matched_jingfang_clues"] if c["name"] == "吴茱萸汤"]
        self.assertEqual(len(wu_hits), 1)

        # Symptom characters like 浮肿 / 轻微 / 数日 must not hallucinate pulses unless pulse clause present
        edema = compose_differentiation("往来寒热 心烦 口苦 头晕 浮肿 小便不利", "沉 紧")
        self.assertEqual(set(edema["recognized_pulses"]), {"沉", "紧"})
        self.assertNotIn("浮", edema["recognized_pulses"])
        non_pulse = compose_differentiation("浮肿 轻微恶寒 咳嗽 数日 缓解")
        self.assertEqual(non_pulse["recognized_pulses"], [])
        explicit_q_pulse = compose_differentiation("浮肿 头晕 脉沉微细")
        self.assertEqual(set(explicit_q_pulse["recognized_pulses"]), {"沉", "微细"})

    def test_frontend_and_pwa_optimization_hooks(self) -> None:
        api_res = self.client.get("/api/stage5/compose", params={"q": "无发热 头痛 呕吐", "pulse": "弦"}).json()
        self.assertIn("发热", api_res["recognized_negations"])
        self.assertIn("negated_terms", api_res["ai_ready_case_packet"])

        js = (ROOT / "web" / "library_stage5.js").read_text(encoding="utf-8")
        for tok in ("recognized_negations", "data-copy-ai", "单方专治统摄", "s5-alt-regimen-card"):
            self.assertIn(tok, js)
