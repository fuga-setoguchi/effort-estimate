# effort-estimate

既存リポジトリに対する改修・機能追加の工数を、決まった手順で算出する Claude スキル

AI に直接「何時間か」を考えさせると、タスクの分解粒度や含める範囲が毎回変わり、結果がブレる。
このスキルでは役割を分け、Claude がコード調査・タスク分解・基準表への分類を行い、時間の計算はスクリプト（`scripts/calc.py`）が行う。
そのため、誰がいつ見積もっても同じ分類なら同じ結果になる。

## 想定している使い方

- 対象は、既存の Web アプリケーションに対する改修・機能追加。基準表の作業種別（API、画面、DB マイグレーション、バッチなど）もこの前提で作ってある。新規開発の全体見積もりや、Web アプリ以外の開発には、基準表の作り直しが要る。
- 受託開発で、先方に見積もりを提示する場面を想定している。

## 出力される数字

| 項目 | 内容 |
|---|---|
| 実作業見込み | AI 支援ありで作業した場合の実際の時間（スケジュール・アサイン用） |
| 対外工数 | AI 支援なしの従来基準で算出した工数（先方提示用） |

### 対外工数の用途

対外工数は、請負（固定額）の見積もりで、成果物の規模を従来の基準で示すための数字。
稼働時間で精算する契約（準委任など）の請求時間には使わない。実際に稼働していない時間を請求することになるため。
先方に提示するときに AI 支援の有無をどう説明するかは、契約と先方との合意に従って利用者が判断する。

### 出力例

記入例（`assets/example_tasks.json`）を計算した結果の冒頭。このあとに工程別内訳、タスク明細、分類の根拠が続く。

```
| 項目 | 実作業見込み（AI支援あり） | 対外工数（従来基準） |
|---|---|---|
| 小計 | 12.25h | 21.75h |
| バッファ（保険・mid: 実作業小計の20%） | 2.5h | 2.5h（実作業と同じ時間） |
| **合計** | **14.75h** | **24.25h** |
| 人日換算（8h/日） | 1.84人日 | 3.03人日 |
```

## 使い方

Claude に「この改修の工数を見積もって」のように依頼すると、スキルが自動で使われる。

## 保存先

見積もり結果は、Markdown（結果）と tasks.json（再計算・実績比較用）の2ファイルで保存される。保存先のフォルダは次の順で決まる。

1. 依頼のときに指定したフォルダ（例：「見積もりは `~/estimates` に保存して」）
2. 環境変数 `EFFORT_ESTIMATE_OUTPUT_DIR` に設定したフォルダ
3. どちらもなければ、Git リポジトリと同じ階層の `docs/` フォルダ

```
project/
├── repo/     ← Git リポジトリ
└── docs/     ← 既定の保存先（リポジトリの外に作られる）
```

既定の保存先はリポジトリの親フォルダに作られる。親フォルダを他の用途で使っている場合は、1 か 2 で保存先を指定する。
毎回同じ場所に保存したい場合は、環境変数を設定しておく。

```
export EFFORT_ESTIMATE_OUTPUT_DIR="$HOME/estimates"
```

## インストール

### Claude Code（プラグインとして）

```
/plugin marketplace add fuga-setoguchi/effort-estimate
/plugin install effort-estimate@effort-estimate
```

### Claude Code（スキルフォルダを直接配置）

`skills/effort-estimate` を `~/.claude/skills/`（全プロジェクト共通）またはプロジェクトの `.claude/skills/` にコピーする。

### claude.ai

`skills/effort-estimate` フォルダを zip にし、Customize > Skills からアップロードする。

このスキルは、対象のコードを読むことと、Python スクリプトを実行することを前提にしている。claude.ai で使う場合は次の点に注意する。

- コード実行が使える状態にしておく。
- 調査対象のコードを Claude が読めるようにする（ファイルを渡すなど）。コードを読めない場合、分類の根拠が弱くなる。
- Git リポジトリの中で実行されないため、既定の保存先は使えない。保存先は Claude が確認する。

## 必要な環境

- Python 3.8 以上（標準ライブラリのみ使用）
- Git（既定の保存先を使う場合）

## 構成

```
skills/effort-estimate/
├── SKILL.md                         # スキル本体（手順）
├── references/
│   ├── estimation_rules.json        # 基準表（作業種別×サイズの時間、補正係数、バッファ率）
│   ├── classification_guide.md      # サイズ・係数の判定基準
│   └── tasks_schema.md              # tasks.json の書き方
├── assets/
│   ├── example_tasks.json           # tasks.json の記入例
│   └── example_tasks_custom.json    # custom タスクと計上しない工程を含む記入例
├── scripts/
│   ├── calc.py                      # 工数計算
│   └── output_path.py               # 保存先パスの決定
└── templates/output.md              # 見積もり結果のテンプレート
```

スクリプト単体でも動作確認できる。

```
python3 skills/effort-estimate/scripts/calc.py skills/effort-estimate/assets/example_tasks.json
python3 skills/effort-estimate/scripts/output_path.py "対応内容" --dir ./estimates
```

tasks.json の項目は [tasks_schema.md](skills/effort-estimate/references/tasks_schema.md) にまとめてある。

## 基準表のカスタマイズ

`references/estimation_rules.json` の数値はすべて仮値。自分やチームの実績に合わせて調整する。

- 時間は `rounding_step`（既定は 0.25h）の単位で切り上げて計算する。値は `rounding_step` の倍数にし、S < M < L になるようにする。丸めた結果サイズの差がなくなる作業種別があると、計算時に警告が出る。
- 形式が正しくない場合、calc.py は計算せずにエラーの内容を表示する。
- 調整したら `version` を上げておくと、結果の末尾にどの基準表で算出したかが表示される。

## テスト

```
python3 -m unittest discover tests
```

## License

MIT
