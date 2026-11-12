#!/usr/bin/env python3
"""工数計算スクリプト

tasks.json（Claude が作成したタスク分類）と estimation_rules.json（基準表）から
実作業見込み（AI支援あり）と対外工数（従来基準）を計算し、Markdown で出力する。

使い方:
    python3 calc.py tasks.json [--rules path/to/estimation_rules.json] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parent.parent / "references" / "estimation_rules.json"
SIZES = ("S", "M", "L")
COEF_LABELS = {"uncertainty": "不確実性", "complexity": "複雑さ", "unfamiliarity": "未経験"}
DEFAULT_CUSTOM_RATIO_THRESHOLD = 0.3


def ceil_step(value: float, step: float) -> float:
    """step 単位で切り上げる（浮動小数の誤差を吸収）。"""
    return math.ceil(round(value / step, 6)) * step


def fmt(value: float) -> str:
    return f"{value:g}"


def esc(value) -> str:
    """Markdown の表の中で崩れないようにする。"""
    return str(value).replace("|", "\\|").replace("\n", " ")


def is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"エラー: ファイルが見つかりません: {path}")
    except (OSError, UnicodeDecodeError) as e:
        sys.exit(f"エラー: ファイルを読めません ({path}): {e}")
    except json.JSONDecodeError as e:
        sys.exit(f"エラー: JSON の形式が正しくありません ({path}): {e}")


def fail(headline: str, errors: list[str]) -> None:
    print(headline, file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    sys.exit(1)


def validate_rules(rules) -> list[str]:
    """基準表の形式を確認する。問題があればエラーメッセージのリストを返す。"""
    if not isinstance(rules, dict):
        return ["最上位はオブジェクト（{...}）にしてください"]

    errors: list[str] = []

    for key in ("hours_per_day", "rounding_step"):
        if not is_num(rules.get(key)) or rules[key] <= 0:
            errors.append(f"{key} は 0 より大きい数値にしてください")

    phases = rules.get("phases")
    if not isinstance(phases, dict) or not phases:
        errors.append("phases は 1 つ以上の工程を持つオブジェクトにしてください")
        phases = {}

    required = rules.get("required_phases")
    if not isinstance(required, list):
        errors.append("required_phases は配列にしてください")
    else:
        for ph in required:
            if not isinstance(ph, str) or ph not in phases:
                errors.append(f"required_phases に phases にない工程があります: {ph!r}")

    work_types = rules.get("work_types")
    if not isinstance(work_types, dict) or not work_types:
        errors.append("work_types は 1 つ以上の作業種別を持つオブジェクトにしてください")
    else:
        for name, wt in work_types.items():
            if not isinstance(wt, dict):
                errors.append(f"work_types.{name} はオブジェクトにしてください")
                continue
            if not isinstance(wt.get("phase"), str) or wt["phase"] not in phases:
                errors.append(f"work_types.{name}.phase が phases にありません: {wt.get('phase')!r}")
            if not isinstance(wt.get("label"), str) or not wt["label"]:
                errors.append(f"work_types.{name}.label がありません")
            for kind in ("actual", "traditional"):
                table = wt.get(kind)
                if not isinstance(table, dict) or any(
                    not is_num(table.get(s)) or table[s] < 0 for s in SIZES
                ):
                    errors.append(f"work_types.{name}.{kind} には S / M / L の数値（0 以上）が必要です")

    coefs = rules.get("coefficients")
    if not isinstance(coefs, dict) or not coefs:
        errors.append("coefficients は 1 つ以上の係数を持つオブジェクトにしてください")
    else:
        for key, table in coefs.items():
            if not isinstance(table, dict) or not table or any(
                not is_num(v) or v <= 0 for v in table.values()
            ):
                errors.append(f"coefficients.{key} は「レベル: 0 より大きい数値」のオブジェクトにしてください")

    buffer_rate = rules.get("buffer_rate")
    if not isinstance(buffer_rate, dict) or not buffer_rate or any(
        not is_num(v) or v < 0 for v in buffer_rate.values()
    ):
        errors.append("buffer_rate は「リスク: 0 以上の数値」のオブジェクトにしてください")

    ratio = rules.get("custom_traditional_ratio")
    if not is_num(ratio) or ratio <= 0:
        errors.append("custom_traditional_ratio は 0 より大きい数値にしてください")

    warn_conf = rules.get("warnings", {})
    if not isinstance(warn_conf, dict):
        errors.append("warnings はオブジェクトにしてください")
    elif "custom_ratio_threshold" in warn_conf and not is_num(warn_conf["custom_ratio_threshold"]):
        errors.append("warnings.custom_ratio_threshold は数値にしてください")

    return errors


def calc_task(index: int, task, rules: dict, errors: list[str]) -> dict | None:
    if not isinstance(task, dict):
        errors.append(f"tasks の {index + 1} 番目はオブジェクト（{{...}}）にしてください")
        return None

    tid = task.get("id")
    if not isinstance(tid, (str, int)) or isinstance(tid, bool) or tid == "":
        errors.append(f"tasks の {index + 1} 番目: id は文字列か数値で指定してください: {tid!r}")
        return None

    name = task.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"[{tid}] name（タスク名）がありません")
        return None

    step = rules["rounding_step"]

    # 補正係数
    coef = 1.0
    coef_detail = {}
    for key, table in rules["coefficients"].items():
        level = task.get(key)
        if not isinstance(level, str) or level not in table:
            errors.append(f"[{tid}] {key} の値が不正です: {level!r}（候補: {', '.join(table)}）")
            return None
        coef *= table[level]
        coef_detail[key] = level

    ttype = task.get("type")
    if ttype == "custom":
        values = [task.get(k) for k in ("optimistic", "likely", "pessimistic")]
        if not all(is_num(v) for v in values):
            errors.append(f"[{tid}] custom には optimistic / likely / pessimistic（数値）が必要です")
            return None
        o, m, p = values
        if o < 0:
            errors.append(f"[{tid}] 三点見積もりは 0 以上にしてください")
            return None
        if not (o <= m <= p):
            errors.append(f"[{tid}] 三点見積もりは 楽観 <= 標準 <= 悲観 にしてください")
            return None
        phase = task.get("phase")
        if not isinstance(phase, str) or phase not in rules["phases"]:
            errors.append(f"[{tid}] custom には phase が必要です（候補: {', '.join(rules['phases'])}）")
            return None
        base_actual = (o + 4 * m + p) / 6
        base_trad = base_actual * rules["custom_traditional_ratio"]
        label = "custom（三点見積もり）"
        size = "-"
    else:
        wt = rules["work_types"].get(ttype) if isinstance(ttype, str) else None
        if wt is None:
            errors.append(f"[{tid}] 未定義の作業種別です: {ttype!r}")
            return None
        size = task.get("size")
        if not isinstance(size, str) or size not in SIZES:
            errors.append(f"[{tid}] size は S / M / L のいずれかにしてください: {size!r}")
            return None
        base_actual = wt["actual"][size]
        base_trad = wt["traditional"][size]
        phase = wt["phase"]
        label = wt["label"]

    reason = task.get("reason")
    evidence = task.get("evidence")
    return {
        "id": tid,
        "name": name,
        "type": ttype,
        "type_label": label,
        "size": size,
        "phase": phase,
        "coefficient": round(coef, 4),
        "coef_detail": coef_detail,
        "actual": ceil_step(base_actual * coef, step),
        "traditional": ceil_step(base_trad * coef, step),
        "reason": reason if isinstance(reason, str) else "",
        "evidence": [str(e) for e in evidence] if isinstance(evidence, list) else [],
    }


def flat_sizes(rules: dict, used_types: set) -> list[str]:
    """丸めた結果、サイズを上げても時間が増えない作業種別を返す。"""
    step = rules["rounding_step"]
    found = []
    for name in sorted(used_types):
        wt = rules["work_types"].get(name)
        if wt is None:
            continue
        for kind in ("actual", "traditional"):
            s, m, l = (ceil_step(wt[kind][size], step) for size in SIZES)
            if not (s < m < l):
                found.append(name)
                break
    return found


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="工数計算")
    ap.add_argument("tasks", type=Path)
    ap.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    ap.add_argument("--json", action="store_true", help="結果を JSON で出力する")
    args = ap.parse_args()

    rules = load_json(args.rules)
    rule_errors = validate_rules(rules)
    if rule_errors:
        fail(f"基準表の形式が正しくありません（{args.rules}）。", rule_errors)

    data = load_json(args.tasks)
    if not isinstance(data, dict):
        fail("計算できませんでした。tasks.json を修正してください。",
             ["最上位はオブジェクト（{...}）にしてください"])

    step = rules["rounding_step"]
    hpd = rules["hours_per_day"]

    errors: list[str] = []
    warnings: list[str] = []

    risk = data.get("project_risk")
    if not isinstance(risk, str) or risk not in rules["buffer_rate"]:
        errors.append(f"project_risk の値が不正です: {risk!r}（候補: {', '.join(rules['buffer_rate'])}）")

    skipped = data.get("skipped_phases")
    if skipped is None:
        skipped = {}
    if not isinstance(skipped, dict):
        errors.append('skipped_phases は {"工程": "計上しない理由"} の形式にしてください')
        skipped = {}
    for ph, why in skipped.items():
        if ph not in rules["phases"]:
            errors.append(f"skipped_phases に未定義の工程があります: {ph!r}（候補: {', '.join(rules['phases'])}）")
        elif not isinstance(why, str) or not why.strip():
            errors.append(f"skipped_phases.{ph} に計上しない理由を書いてください")

    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        errors.append("tasks は配列（[...]）にしてください")
        tasks = []
    elif not tasks:
        errors.append("tasks が空です")

    results = [r for i, t in enumerate(tasks) if (r := calc_task(i, t, rules, errors)) is not None]

    ids = [r["id"] for r in results]
    dup = sorted({str(i) for i in ids if ids.count(i) > 1})
    if dup:
        errors.append(f"タスクの id が重複しています: {', '.join(dup)}")

    if errors:
        fail("計算できませんでした。tasks.json を修正してください。", errors)

    # 必須工程のチェック
    present = {r["phase"] for r in results}
    for ph in rules["required_phases"]:
        if ph not in present and ph not in skipped:
            warnings.append(
                f"必須工程「{rules['phases'][ph]}」のタスクがありません。"
                f"不要なら skipped_phases に理由を書いてください。"
            )
    for ph in skipped:
        if ph in present:
            warnings.append(
                f"skipped_phases に書かれた工程「{rules['phases'][ph]}」のタスクが計上されています。"
                f"どちらかを見直してください。"
            )

    # 集計
    sub_actual = sum(r["actual"] for r in results)
    sub_trad = sum(r["traditional"] for r in results)
    rate = rules["buffer_rate"][risk]
    buf_actual = ceil_step(sub_actual * rate, step)
    # バッファは「想定外の作業に備えた予備の時間」。実際に対応するのは AI 支援ありの体制なので、
    # 実作業見込みで算出したバッファの時間を、そのまま対外工数にも保険として載せる。
    buf_trad = buf_actual
    total_actual = sub_actual + buf_actual
    total_trad = sub_trad + buf_trad

    custom_actual = sum(r["actual"] for r in results if r["type"] == "custom")
    threshold = rules.get("warnings", {}).get("custom_ratio_threshold", DEFAULT_CUSTOM_RATIO_THRESHOLD)
    if sub_actual and custom_actual / sub_actual > threshold:
        warnings.append(
            f"custom タスクが実作業見込みの {custom_actual / sub_actual:.0%} を占めています"
            f"（目安 {threshold:.0%} 以下）。既存の作業種別に寄せられないか見直してください。"
        )

    no_reason = [str(r["id"]) for r in results if not r["reason"].strip()]
    if no_reason:
        warnings.append(f"分類の根拠（reason）が空のタスクがあります: {', '.join(no_reason)}")

    flat = flat_sizes(rules, {r["type"] for r in results})
    if flat:
        warnings.append(
            f"基準表の値を {fmt(step)}h 単位に丸めると、サイズを上げても時間が増えない作業種別があります: "
            f"{', '.join(flat)}。基準表の値か rounding_step を見直してください。"
        )

    by_phase = []
    for ph, ph_label in rules["phases"].items():
        a = sum(r["actual"] for r in results if r["phase"] == ph)
        t = sum(r["traditional"] for r in results if r["phase"] == ph)
        by_phase.append({"phase": ph, "label": ph_label, "actual": a, "traditional": t})

    summary = {
        "rules_version": rules.get("version"),
        "project_risk": risk,
        "buffer_rate": rate,
        "subtotal": {"actual": sub_actual, "traditional": sub_trad},
        "buffer": {"actual": buf_actual, "traditional": buf_trad},
        "total": {"actual": total_actual, "traditional": total_trad},
        "total_days": {
            "actual": round(total_actual / hpd, 2),
            "traditional": round(total_trad / hpd, 2),
        },
        "hours_per_day": hpd,
        "by_phase": by_phase,
        "tasks": results,
        "skipped_phases": skipped,
        "warnings": warnings,
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    out = []
    out.append("### 工数サマリ\n")
    out.append("| 項目 | 実作業見込み（AI支援あり） | 対外工数（従来基準） |")
    out.append("|---|---|---|")
    out.append(f"| 小計 | {fmt(sub_actual)}h | {fmt(sub_trad)}h |")
    out.append(
        f"| バッファ（保険・{risk}: 実作業小計の{rate:.0%}） | {fmt(buf_actual)}h | {fmt(buf_trad)}h（実作業と同じ時間） |"
    )
    out.append(f"| **合計** | **{fmt(total_actual)}h** | **{fmt(total_trad)}h** |")
    out.append(
        f"| 人日換算（{fmt(hpd)}h/日） | {summary['total_days']['actual']:g}人日 "
        f"| {summary['total_days']['traditional']:g}人日 |"
    )
    out.append("")
    out.append("### 工程別内訳\n")
    out.append("| 工程 | 実作業見込み | 対外工数 |")
    out.append("|---|---|---|")
    for p in by_phase:
        out.append(f"| {esc(p['label'])} | {fmt(p['actual'])}h | {fmt(p['traditional'])}h |")
    if skipped:
        out.append("")
        out.append("計上しなかった工程：")
        for ph, why in skipped.items():
            out.append(f"- {rules['phases'][ph]}：{why}")
    out.append("")
    out.append("### タスク明細\n")
    out.append("| ID | タスク | 作業種別 | サイズ | 係数 | 実作業 | 対外 |")
    out.append("|---|---|---|---|---|---|---|")
    for r in results:
        levels = " / ".join(f"{COEF_LABELS.get(k, k)}:{v}" for k, v in r["coef_detail"].items())
        coef_str = f"{r['coefficient']:g}（{levels}）"
        out.append(
            f"| {esc(r['id'])} | {esc(r['name'])} | {esc(r['type_label'])} | {r['size']} | {esc(coef_str)} "
            f"| {fmt(r['actual'])}h | {fmt(r['traditional'])}h |"
        )
    out.append("")
    out.append("### 分類の根拠\n")
    for r in results:
        reason = " ".join(r["reason"].split()) or "（記載なし）"
        line = f"- {r['id']}：{reason}"
        if r["evidence"]:
            line += "（確認したファイル：" + "、".join(f"`{e}`" for e in r["evidence"]) + "）"
        out.append(line)
    if warnings:
        out.append("")
        out.append("### 計算時の警告\n")
        for w in warnings:
            out.append(f"- ⚠️ {w}")
    out.append("")
    out.append(f"<sub>基準表 v{rules.get('version')} で算出</sub>")
    print("\n".join(out))


if __name__ == "__main__":
    main()
