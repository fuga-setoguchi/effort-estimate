"""calc.py のテスト（標準ライブラリのみ）。

    python3 -m unittest discover tests
"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "effort-estimate"
CALC = SKILL / "scripts" / "calc.py"
RULES = SKILL / "references" / "estimation_rules.json"
EXAMPLE = SKILL / "assets" / "example_tasks.json"
EXAMPLE_CUSTOM = SKILL / "assets" / "example_tasks_custom.json"

COEF = {"uncertainty": "low", "complexity": "low", "unfamiliarity": "none"}
SKIP_ALL_BUT_IMPL = {"investigation": "x", "test": "x", "review": "x", "release": "x"}


def task(**kw):
    t = {"id": "T1", "name": "タスク", "type": "api_endpoint", "size": "S", "reason": "理由"}
    t.update(COEF)
    t.update(kw)
    return t


class CalcTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def run_calc(self, tasks_path, *args, env=None):
        return subprocess.run(
            [sys.executable, str(CALC), str(tasks_path), *args],
            capture_output=True, encoding="utf-8", env=env,
        )

    def run_data(self, data, *args):
        return self.run_calc(self.write("tasks.json", data), *args)

    def summary(self, data, *args):
        r = self.run_data(data, "--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def assert_error(self, data, message, *args):
        r = self.run_data(data, *args)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(message, r.stderr)
        self.assertNotIn("Traceback", r.stderr)


class ExampleTest(CalcTestCase):
    def test_example(self):
        r = self.run_calc(EXAMPLE, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual(s["subtotal"], {"actual": 13.0, "traditional": 22.0})
        self.assertEqual(s["buffer"], {"actual": 3.0, "traditional": 3.0})
        self.assertEqual(s["total"], {"actual": 16.0, "traditional": 25.0})
        self.assertEqual(s["warnings"], [])

    def test_example_custom(self):
        r = self.run_calc(EXAMPLE_CUSTOM, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual(s["total"], {"actual": 16.0, "traditional": 24.5})
        self.assertEqual(list(s["skipped_phases"]), ["release"])
        self.assertEqual(s["warnings"], [])

    def test_totals_are_consistent(self):
        for path in (EXAMPLE, EXAMPLE_CUSTOM):
            s = json.loads(self.run_calc(path, "--json").stdout)
            for kind in ("actual", "traditional"):
                self.assertEqual(sum(t[kind] for t in s["tasks"]), s["subtotal"][kind])
                self.assertEqual(sum(p[kind] for p in s["by_phase"]), s["subtotal"][kind])
                self.assertEqual(s["subtotal"][kind] + s["buffer"][kind], s["total"][kind])

    def test_markdown_output(self):
        r = self.run_calc(EXAMPLE)
        self.assertEqual(r.returncode, 0, r.stderr)
        for heading in ("### 工数サマリ", "### 工程別内訳", "### タスク明細", "### 分類の根拠"):
            self.assertIn(heading, r.stdout)
        self.assertIn("| **合計** | **16h** | **25h** |", r.stdout)
        self.assertNotIn("### 計算時の警告", r.stdout)


class CalculationTest(CalcTestCase):
    def test_coefficient_and_rounding(self):
        # api_endpoint S: 実作業 1h / 対外 2h。係数 1.2 * 1.15 = 1.38 → 0.5h 単位で切り上げ
        s = self.summary({
            "project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL,
            "tasks": [task(uncertainty="mid", complexity="mid")],
        })
        self.assertEqual(s["tasks"][0]["coefficient"], 1.38)
        self.assertEqual(s["tasks"][0]["actual"], 1.5)
        self.assertEqual(s["tasks"][0]["traditional"], 3.0)

    def test_buffer_uses_actual_subtotal(self):
        # 実作業小計 1h の 30% = 0.3h → 0.5h。対外にも同じ時間を載せる
        s = self.summary({
            "project_risk": "high", "skipped_phases": SKIP_ALL_BUT_IMPL, "tasks": [task()],
        })
        self.assertEqual(s["buffer"], {"actual": 0.5, "traditional": 0.5})
        self.assertEqual(s["total"], {"actual": 1.5, "traditional": 2.5})

    def test_custom_pert(self):
        # (1 + 4*2 + 9) / 6 = 3h、対外は 1.8 倍 = 5.4h → 5.5h
        s = self.summary({
            "project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL,
            "tasks": [task(type="custom", phase="implementation",
                           optimistic=1, likely=2, pessimistic=9)],
        })
        self.assertEqual(s["tasks"][0]["actual"], 3.0)
        self.assertEqual(s["tasks"][0]["traditional"], 5.5)

    def test_every_work_type_grows_with_size(self):
        rules = json.loads(RULES.read_text(encoding="utf-8"))
        step = rules["rounding_step"]
        for name, wt in rules["work_types"].items():
            for kind in ("actual", "traditional"):
                s, m, l = (wt[kind][size] for size in ("S", "M", "L"))
                self.assertTrue(s < m < l, f"{name}.{kind}")
                for v in (s, m, l):
                    self.assertEqual(v % step, 0, f"{name}.{kind} は {step} の倍数にする")
            for size in ("S", "M", "L"):
                self.assertLessEqual(wt["actual"][size], wt["traditional"][size], name)


class WarningTest(CalcTestCase):
    def test_missing_required_phase(self):
        s = self.summary({"project_risk": "low", "tasks": [task()]})
        self.assertEqual(sum("必須工程" in w for w in s["warnings"]), 4)

    def test_skipped_phases_null(self):
        s = self.summary({"project_risk": "low", "skipped_phases": None, "tasks": [task()]})
        self.assertEqual(sum("必須工程" in w for w in s["warnings"]), 4)

    def test_skipped_phase_with_task(self):
        skipped = dict(SKIP_ALL_BUT_IMPL, implementation="x")
        s = self.summary({"project_risk": "low", "skipped_phases": skipped, "tasks": [task()]})
        self.assertTrue(any("計上されています" in w for w in s["warnings"]))

    def test_empty_reason(self):
        s = self.summary({
            "project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL, "tasks": [task(reason="")],
        })
        self.assertTrue(any("reason" in w and "T1" in w for w in s["warnings"]))

    def test_custom_ratio(self):
        s = self.summary({
            "project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL,
            "tasks": [task(type="custom", phase="implementation",
                           optimistic=1, likely=2, pessimistic=3)],
        })
        self.assertTrue(any("custom" in w for w in s["warnings"]))

    def test_flat_sizes(self):
        rules = json.loads(RULES.read_text(encoding="utf-8"))
        rules["work_types"]["ui_minor"]["actual"] = {"S": 0.25, "M": 0.5, "L": 1}
        rules_path = self.write("rules.json", rules)
        data = {"project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL,
                "tasks": [task(type="ui_minor")]}
        s = self.summary(data, "--rules", str(rules_path))
        self.assertTrue(any("ui_minor" in w for w in s["warnings"]))
        # 既定の基準表では出ない
        self.assertEqual(self.summary(data)["warnings"], [])


class OutputTest(CalcTestCase):
    def test_pipe_is_escaped(self):
        r = self.run_data({
            "project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL,
            "tasks": [task(name="A|B")],
        })
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("A\\|B", r.stdout)

    def test_reason_and_evidence_are_listed(self):
        r = self.run_data({
            "project_risk": "low", "skipped_phases": SKIP_ALL_BUT_IMPL,
            "tasks": [task(reason="既存と同じ", evidence=["app/A.php"])],
        })
        self.assertIn("- T1：既存と同じ（確認したファイル：`app/A.php`）", r.stdout)

    def test_non_utf8_terminal(self):
        # cp932 の端末でも、警告の絵文字で落ちない
        env = dict(os.environ, PYTHONIOENCODING="cp932")
        path = self.write("tasks.json", {"project_risk": "low", "tasks": [task()]})
        r = subprocess.run([sys.executable, str(CALC), str(path)], capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("⚠️", r.stdout.decode("utf-8"))


class TasksErrorTest(CalcTestCase):
    def test_top_level_is_not_object(self):
        self.assert_error([], "最上位はオブジェクト")

    def test_tasks_is_not_list(self):
        self.assert_error({"project_risk": "low", "tasks": {"a": 1}}, "tasks は配列")

    def test_tasks_is_empty(self):
        self.assert_error({"project_risk": "low", "tasks": []}, "tasks が空です")

    def test_task_is_not_object(self):
        self.assert_error({"project_risk": "low", "tasks": ["x"]}, "1 番目はオブジェクト")

    def test_bad_values(self):
        cases = [
            ({"project_risk": ["x"], "tasks": [task()]}, "project_risk の値が不正"),
            ({"project_risk": "low", "tasks": [task(id=[1])]}, "id は文字列か数値"),
            ({"project_risk": "low", "tasks": [task(name="")]}, "name（タスク名）がありません"),
            ({"project_risk": "low", "tasks": [task(type="unknown")]}, "未定義の作業種別"),
            ({"project_risk": "low", "tasks": [task(type=["x"])]}, "未定義の作業種別"),
            ({"project_risk": "low", "tasks": [task(size="XL")]}, "size は S / M / L"),
            ({"project_risk": "low", "tasks": [task(uncertainty="x")]}, "uncertainty の値が不正"),
            ({"project_risk": "low", "tasks": [task(complexity={})]}, "complexity の値が不正"),
            ({"project_risk": "low", "tasks": [task(), task()]}, "id が重複"),
            ({"project_risk": "low", "skipped_phases": [], "tasks": [task()]}, "skipped_phases は"),
            ({"project_risk": "low", "skipped_phases": {"foo": "x"}, "tasks": [task()]}, "未定義の工程"),
            ({"project_risk": "low", "skipped_phases": {"test": ""}, "tasks": [task()]}, "理由を書いてください"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                self.assert_error(data, message)

    def test_custom_errors(self):
        def custom(**kw):
            base = dict(type="custom", phase="implementation", optimistic=1, likely=2, pessimistic=3)
            base.update(kw)
            return {"project_risk": "low", "tasks": [task(**base)]}

        cases = [
            (custom(optimistic=-5, likely=-3, pessimistic=-1), "0 以上"),
            (custom(optimistic=3, likely=2, pessimistic=1), "楽観 <= 標準 <= 悲観"),
            (custom(likely="2"), "（数値）が必要"),
            (custom(phase=None), "custom には phase が必要"),
            (custom(phase="unknown"), "custom には phase が必要"),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                self.assert_error(data, message)

    def test_file_errors(self):
        r = self.run_calc(self.tmp / "none.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ファイルが見つかりません", r.stderr)

        broken = self.tmp / "broken.json"
        broken.write_text("{", encoding="utf-8")
        r = self.run_calc(broken)
        self.assertEqual(r.returncode, 1)
        self.assertIn("JSON の形式が正しくありません", r.stderr)


class RulesErrorTest(CalcTestCase):
    def assert_rules_error(self, mutate, message):
        rules = copy.deepcopy(json.loads(RULES.read_text(encoding="utf-8")))
        mutate(rules)
        rules_path = self.write("rules.json", rules)
        r = self.run_calc(EXAMPLE, "--rules", str(rules_path))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("基準表の形式が正しくありません", r.stderr)
        self.assertIn(message, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_missing_keys(self):
        for key in ("hours_per_day", "rounding_step", "phases", "required_phases",
                    "work_types", "coefficients", "buffer_rate", "custom_traditional_ratio"):
            with self.subTest(key=key):
                self.assert_rules_error(lambda r, key=key: r.pop(key), key)

    def test_bad_work_type(self):
        def no_size(r):
            del r["work_types"]["api_endpoint"]["actual"]["M"]

        def bad_phase(r):
            r["work_types"]["api_endpoint"]["phase"] = "unknown"

        self.assert_rules_error(no_size, "work_types.api_endpoint.actual")
        self.assert_rules_error(bad_phase, "work_types.api_endpoint.phase")

    def test_bad_numbers(self):
        def zero_step(r):
            r["rounding_step"] = 0

        def text_coef(r):
            r["coefficients"]["uncertainty"]["mid"] = "1.2"

        self.assert_rules_error(zero_step, "rounding_step")
        self.assert_rules_error(text_coef, "coefficients.uncertainty")

    def test_rules_is_not_object(self):
        rules_path = self.write("rules.json", [])
        r = self.run_calc(EXAMPLE, "--rules", str(rules_path))
        self.assertEqual(r.returncode, 1)
        self.assertIn("最上位はオブジェクト", r.stderr)


if __name__ == "__main__":
    unittest.main()
