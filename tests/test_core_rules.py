"""PawLife 核心规则的最小回归测试。

运行：
    python -m unittest discover -s tests -v

这些测试只覆盖本轮修改涉及的纯规则，不启动 FastAPI 服务。
"""

import unittest
from datetime import date, timedelta

import pawlife_web as app


class HighRiskScanTests(unittest.TestCase):
    def test_direct_high_risk_keyword(self):
        self.assertEqual(app._scan_high_risk_text("今天持续呕吐两次"), "持续呕吐")

    def test_common_synonym(self):
        self.assertEqual(app._scan_high_risk_text("从下午开始一直吐"), "持续呕吐")
        self.assertEqual(app._scan_high_risk_text("大便带血"), "便血")

    def test_normal_symptom_is_not_high_risk(self):
        self.assertIsNone(app._scan_high_risk_text("今天有点软便，但精神正常"))
        self.assertIsNone(app._scan_high_risk_text("偶尔抓痒"))
        # 单个“呕吐”保留为普通观察项，不自动升级为高风险。
        self.assertIsNone(app._scan_high_risk_text("呕吐"))

    def test_negated_expression_is_not_high_risk(self):
        self.assertIsNone(app._scan_high_risk_text("没有持续呕吐，精神正常"))
        self.assertIsNone(app._scan_high_risk_text("未见便血"))
        self.assertIsNone(app._scan_high_risk_text("无明显的呼吸困难"))

    def test_negated_phrase_does_not_hide_later_risk(self):
        self.assertEqual(app._scan_high_risk_text("没有持续呕吐，但今天便血"), "便血")

    def test_historical_resolved_description_is_not_high_risk(self):
        self.assertIsNone(app._scan_high_risk_text("上次持续呕吐，今天已经恢复"))
        self.assertIsNone(app._scan_high_risk_text("昨天便血，今天精神正常"))
        self.assertIsNone(app._scan_high_risk_text("上次持续呕吐，今天没有呕吐"))

    def test_historical_description_with_new_risk_still_triggers(self):
        self.assertEqual(app._scan_high_risk_text("上次持续呕吐，今天又吐了"), "持续呕吐")

    def test_empty_and_invalid_input(self):
        self.assertIsNone(app._scan_high_risk_text(""))
        self.assertIsNone(app._scan_high_risk_text(None))

    def test_event_text_includes_symptoms_and_note(self):
        text = app._event_risk_text({
            "symptoms": ["呕吐", "拉稀"],
            "note": "一直吐，精神差",
        })
        self.assertIn("呕吐", text)
        self.assertIn("拉稀", text)
        self.assertIn("一直吐", text)


class DietRuleTests(unittest.TestCase):
    def test_rer_linear_range(self):
        self.assertEqual(app._calc_rer(10), 370.0)

    def test_rer_power_formula(self):
        self.assertAlmostEqual(app._calc_rer(1), 70.0, places=2)

    def test_daily_grams_returns_expected_keys(self):
        birthday = date.today() - timedelta(days=365 * 3)
        plan = app._calc_daily_grams(birthday, 10, "是", "female")
        for key in ("rer", "der", "total_g", "protein_g", "carb_g", "veggie_g", "age_stage"):
            self.assertIn(key, plan)
        self.assertGreater(plan["total_g"], 0)

    def test_allergen_filter(self):
        self.assertFalse(app._filter_allergen_foods("鸡胸肉", "鸡肉"))
        self.assertTrue(app._filter_allergen_foods("南瓜", "鸡肉"))


class BehaviorTreeTests(unittest.TestCase):
    def test_unknown_breed_uses_default(self):
        result = app.analyze_behavior("未知品种", ["呕吐"])
        self.assertEqual(len(result["results"]), 1)
        self.assertIn("advice", result["results"][0])

    def test_know_symptom_returns_advice(self):
        result = app.analyze_behavior("柯基", ["跛行"])
        self.assertEqual(result["results"][0]["symptom"], "跛行")
        self.assertIn("level", result["results"][0])


if __name__ == "__main__":
    unittest.main()
