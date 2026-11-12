# effort-estimate

既存リポジトリに対する改修・機能追加の工数を、決まった手順で算出する Claude スキルです。

AI に直接「何時間か」を考えさせると、タスクの分解粒度や含める範囲が毎回変わり、結果がブレます。
このスキルでは役割を分け、Claude がコード調査・タスク分解・基準表への分類を行い、時間の計算はスクリプト（`scripts/calc.py`）が行います。
そのため、誰がいつ見積もっても同じ分類なら同じ結果になります。

## 出力される数字

| 項目 | 内容 |
|---|---|
| 実作業見込み | AI 支援ありで作業した場合の実際の時間（スケジュール・アサイン用） |
| 対外工数 | AI 支援なしの従来基準で算出した工数（先方提示用） |

見積もり結果は Git リポジトリと同じ階層の `docs/` フォルダに、Markdown（結果）と tasks.json（再計算・実績比較用）として保存されます。

## 使い方

Claude に「この改修の工数を見積もって」のように依頼すると、スキルが自動で使われます。

## インストール

### Claude Code（プラグインとして）

```
/plugin marketplace add <your-github-user>/effort-estimate
/plugin install effort-estimate@effort-estimate
```

### Claude Code（スキルフォルダを直接配置）

`skills/effort-estimate` を `~/.claude/skills/`（全プロジェクト共通）またはプロジェクトの `.claude/skills/` にコピーします。

### claude.ai

`skills/effort-estimate` フォルダを zip にし、Customize > Skills からアップロードします。

## 構成

```
skills/effort-estimate/
├── SKILL.md                         # スキル本体（手順）
├── references/
│   ├── estimation_rules.json        # 基準表（作業種別×サイズの時間、補正係数、バッファ率）
│   └── classification_guide.md      # サイズ・係数の判定基準
├── assets/example_tasks.json        # tasks.json の記入例
├── scripts/
│   ├── calc.py                      # 工数計算
│   └── output_path.py               # 保存先パスの決定
└── templates/output.md              # 見積もり結果のテンプレート
```

スクリプト単体でも動作確認できます（Python 3.8 以上）。

```
python3 skills/effort-estimate/scripts/calc.py skills/effort-estimate/assets/example_tasks.json
```

## 基準表のカスタマイズ

`references/estimation_rules.json` の数値はすべて仮値です。自分やチームの実績に合わせて調整してください。
調整したら `version` を上げておくと、結果の末尾にどの基準表で算出したかが表示されます。

## License

MIT
