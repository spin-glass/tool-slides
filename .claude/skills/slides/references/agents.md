# Claude Code 以外のエージェントで使うとき

slides と design-doc の検査（lint・check_doc）は、スキルの frontmatter の `hooks`（Stop hook）で自動で走る。
ただし frontmatter の `hooks` を読むのは Claude Code だけで、Devin CLI などは読まない。
hook が無くても検査が抜けないよう、**SKILL.md の検証の手順（slides のフェーズ4、design-doc のフェーズ2.1・2.2の検査）は、どのエージェントでも終える前に自分でコマンドを走らせる。** hook は、走らせ忘れたときの保険として置く。

## Claude Code

設定は要らない。frontmatter の `hooks` が、プロジェクトの `.claude/skills/<スキル>/scripts/` → `~/.claude/skills/<スキル>/scripts/` の順に検査を探して走らせる。

## Devin CLI

hook と実行の許可を、リポジトリの `.devin/` に置く（tool-slides には置いてある）。他のリポジトリでは、パスを `$HOME/.claude/skills/...`（ユーザーレベルのスキル）にする。

`.devin/hooks.v1.json`（Stop で2つの検査を走らせる）:

```json
{
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "CLAUDE_PROJECT_DIR=\"$DEVIN_PROJECT_DIR\" python3 \"$HOME/.claude/skills/design-doc/scripts/check_doc.py\" --hook",
          "timeout": 60
        },
        {
          "type": "command",
          "command": "CLAUDE_PROJECT_DIR=\"$DEVIN_PROJECT_DIR\" python3 \"$HOME/.claude/skills/slides/scripts/lint_slides.py\" --hook",
          "timeout": 30
        }
      ]
    }
  ]
}
```

`.devin/config.json`（実行の許可。書き方は `Exec(コマンド)` で、Claude Code の `Bash(…)` の書き方とは違う）:

```json
{
  "permissions": {
    "allow": [
      "Exec(python3)",
      "Exec(quarto)",
      "Exec(.venv/bin/python)",
      "Exec(/Users/<you>/.claude/skills/slides/scripts/render_check.sh)"
    ]
  }
}
```

- 検査は `CLAUDE_PROJECT_DIR` で対象のリポジトリを知るので、`$DEVIN_PROJECT_DIR` を渡す。
- `--hook` は git で変更のあるデッキ・設計書だけを見る（tool-slides の外では `decks/` に置いていないデッキは見ない）。リポジトリの外のデッキは、手順どおり `lint_slides.py <デッキ>/index.qmd` を自分で走らせる。

## hook が無いエージェント

手順の中のコマンドを、終える前に自分で走らせる。最低限は次の3つ。

```bash
python3 ~/.claude/skills/slides/scripts/lint_slides.py <デッキ>/index.qmd          # block を0にする
~/.claude/skills/slides/scripts/render_check.sh <デッキ>                          # WARNING を0にし、全枚を目視する
python3 ~/.claude/skills/design-doc/scripts/check_doc.py --render <案件>/design/<文書名>.md   # 設計書があるとき
```
