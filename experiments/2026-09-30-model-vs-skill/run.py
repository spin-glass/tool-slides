#!/usr/bin/env python3
"""検証の実行: 条件ごとに新しい作業場所を作り、claude -p を走らせ、ログと成果物を集める。

    python run.py run image fable S3 1          # 課題 image、モデル fable、スキル S3、1回目
    python run.py run gate opus S3 1 --natural  # ゲート課題。--natural は `/slides` を付けない
    python run.py list

作業場所はリポジトリの外（環境変数 MVS_WORK。既定は $TMPDIR/tool-slides-mvs）に作る。
子プロセスには CLAUDE* の環境変数を渡さない（親セッションの effort などを引き継がないため）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORK = Path(os.environ.get("MVS_WORK", Path(tempfile.gettempdir()) / "tool-slides-mvs"))

MODELS = {"fable": "claude-fable-5-1", "opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
          "haiku": "claude-haiku-4-5-20251001"}
SKILLS = {"S0": None, "S1": "7b4428f", "S3": "769927d"}       # スキルを取り出すコミット
# (依頼文, 最大ターン, 予算USD)。under は gate と同じ依頼文（聴衆・行動・時間なし）で、最後まで作らせる
TASKS = {"image": ("prompt_image.md", 60, 12.0), "gate": ("prompt_gate.md", 8, 2.0), "under": ("prompt_gate.md", 60, 12.0)}
DECK = "decks/farm-errors"
APPROVE = "承認します。このまま最後まで作ってください。"
# under で質問が返ってきたときの答え（image の依頼文と同じ内容）
ANSWER = (HERE / "task/prompt_image.md").read_text().split("\n\n", 1)[1].strip()
MAX_FOLLOWUPS = 2
EFFORT = "high"
ALLOWED = "Bash,Read,Write,Edit,Skill,ToolSearch"
DISALLOWED = ("Agent,Workflow,Artifact,WebFetch,WebSearch,CronCreate,CronDelete,RemoteTrigger,PushNotification,"
              "SendMessage,DesignSync,ScheduleWakeup,EnterWorktree")
TIMEOUT_S = 45 * 60

QUARTO_YML = """project:
  type: default
  render:
    - "decks/**/index.qmd"
  output-dir: _output

lang: ja

# HTML コメントだけの段落を出力から除く
filters:
  - filters/strip-comments.lua

# コードセルは .venv の Jupyter で実行する（環境変数 QUARTO_PYTHON）
execute:
  echo: false
  warning: false
  freeze: auto

format:
  revealjs:
    theme: [default, theme/custom.scss]
    slide-number: true
    hash-type: number
    transition: none
    width: 1280
    height: 720
    margin: 0.06
    fig-width: 10
    fig-height: 4.2
    embed-resources: false
"""
LUA = """-- HTML コメントだけの段落を出力から除く（最初の見出しより前に残ると空のスライドになるため）。
function RawBlock(el)
  if el.format:match("html") and el.text:match("^%s*<!%-%-.-%-%->%s*$") then
    local rest = el.text:gsub("<!%-%-.-%-%->", ""):gsub("%s", "")
    if rest == "" then
      return {}
    end
  end
end
"""
GITIGNORE = ".venv/\n_output/\n_freeze/\n.quarto/\ndecks/**/*_files/\ndecks/**/_check/\n__pycache__/\n.DS_Store\n"


def sh(cmd, cwd=None, **kw):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, **kw)


def build_workspace(ws: Path, skill: str) -> None:
    ws.mkdir(parents=True)
    (ws / "_quarto.yml").write_text(QUARTO_YML)
    (ws / "filters").mkdir()
    (ws / "filters/strip-comments.lua").write_text(LUA)
    (ws / "theme").mkdir()
    shutil.copy(ROOT / "theme/custom.scss", ws / "theme/custom.scss")
    shutil.copy(ROOT / "requirements.txt", ws / "requirements.txt")
    (ws / ".gitignore").write_text(GITIGNORE)
    shutil.copy(HERE / "task/workspace_README.md", ws / "README.md")
    shutil.copytree(HERE / "task/data", ws / DECK / "data")
    commit = SKILLS[skill]
    if commit:
        tar = subprocess.run(["git", "archive", commit, ".claude/skills/slides", "decks/_template"], cwd=ROOT,
                             check=True, capture_output=True)
        subprocess.run(["tar", "-x", "-C", str(ws)], input=tar.stdout, check=True)
        skill_md = ws / ".claude/skills/slides/SKILL.md"
        text = skill_md.read_text()
        text2 = re.sub(r"、見本は `decks/2026-09-30-outlier-threshold-images/`（閾値の移動）", "", text)   # 見本デッキは置かない
        skill_md.write_text(text2)
    sh(["uv", "venv", "-q", str(ws / ".venv"), "--python", "3.13"])
    sh(["uv", "pip", "install", "-q", "--python", str(ws / ".venv/bin/python"), "-r", str(ws / "requirements.txt")])
    sh(["git", "init", "-q", "-b", "main"], cwd=ws)
    sh(["git", "add", "-A"], cwd=ws)
    sh(["git", "-c", "user.name=mvs", "-c", "user.email=mvs@example.invalid", "commit", "-q", "-m", "init"], cwd=ws)


def child_env(ws: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")}
    env["QUARTO_PYTHON"] = str(ws / ".venv/bin/python")
    return env


def call_claude(ws: Path, log: Path, prompt: str, model: str, max_turns: int, budget: float, resume: str | None) -> dict:
    cmd = ["claude", "-p", prompt, "--model", MODELS[model], "--effort", EFFORT, "--permission-mode", "acceptEdits",
           "--allowedTools", ALLOWED, "--disallowedTools", DISALLOWED,
           "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--output-format", "stream-json", "--verbose", "--include-hook-events",
           "--max-turns", str(max_turns), "--max-budget-usd", str(budget)]
    if resume:
        cmd += ["--resume", resume]
    t0 = time.time()
    with open(log, "w") as out, open(log.with_suffix(".err"), "w") as err:
        try:
            proc = subprocess.run(cmd, cwd=ws, env=child_env(ws), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                  timeout=TIMEOUT_S)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = -9
    result = {}
    for line in open(log):
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") == "result":
            result = d
    return {"exit": code, "wall_s": round(time.time() - t0), "result": result}


def find_deck(ws: Path) -> Path | None:
    """作られたデッキ。保存先を指定しない依頼（under）では、_template 以外でいちばん新しい index.qmd。"""
    fixed = ws / DECK / "index.qmd"
    if fixed.exists():
        return fixed
    others = [p for p in (ws / "decks").glob("*/index.qmd") if p.parent.name != "_template"]
    return max(others, key=lambda p: p.stat().st_mtime) if others else None


def needs_followup(ws: Path) -> bool:
    qmd = find_deck(ws)
    return qmd is None or bool(re.search(r"<!--\s*status:\s*ghost\s*-->", qmd.read_text()))


def summarize(run_dir: Path) -> dict:
    """ログから、使った道具・スキル・フックの block 回数・最後の発言を取り出す。"""
    tools: dict[str, int] = {}
    skills: list[str] = []
    hook_blocks = stop_hooks = stops = 0
    init_skills: list[str] = []
    final = ""
    limits: dict = {}
    for log in sorted(run_dir.glob("turn*.jsonl")):
        for line in open(log):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "system" and d.get("subtype") == "init":
                init_skills = d.get("skills") or []
            if d.get("type") == "system" and d.get("subtype") == "hook_response" and d.get("hook_event") == "Stop":
                stop_hooks += 1
                if '"decision": "block"' in (d.get("stdout") or ""):
                    hook_blocks += 1
            if d.get("type") == "rate_limit_event":
                limits = {k: v.get("utilization") for k, v in
                          (d.get("rate_limit_info", {}).get("unifiedWindows") or {}).items()}
                limits["status"] = d.get("rate_limit_info", {}).get("status")
            if d.get("type") == "assistant":
                for c in d["message"].get("content", []):
                    if c.get("type") == "tool_use":
                        tools[c["name"]] = tools.get(c["name"], 0) + 1
                        if c["name"] == "Skill":
                            skills.append(str(c.get("input", {}).get("skill")))
            if d.get("type") == "result":
                final = d.get("result") or final
                stops += 1
    return {"tools": tools, "skill_calls": skills, "slides_skill_listed": "slides" in init_skills,
            "stop_hook_responses": stop_hooks, "stop_hook_blocks": hook_blocks, "rate_limits": limits,
            "final_message": final}


def run(task: str, model: str, skill: str, rep: str, natural: bool = False) -> None:
    prompt_file, max_turns, budget = TASKS[task]
    variant = "-nat" if natural else ""
    run_id = f"{task}-{model}-{skill}{variant}-r{rep}"
    run_dir = WORK / "runs" / run_id
    if run_dir.exists():
        sys.exit(f"既にある: {run_dir}")
    ws = run_dir / "ws"
    build_workspace(ws, skill)
    prompt = (HERE / "task" / prompt_file).read_text().strip()
    if skill != "S0" and not natural:
        prompt = "/slides " + prompt
    calls = [call_claude(ws, run_dir / "turn1.jsonl", prompt, model, max_turns, budget, None)]
    followups = 0
    while task in ("image", "under") and followups < MAX_FOLLOWUPS and needs_followup(ws):
        session = calls[-1]["result"].get("session_id")
        if not session:
            break
        followups += 1
        reply = ANSWER if task == "under" and followups == 1 else APPROVE
        calls.append(call_claude(ws, run_dir / f"turn{followups + 1}.jsonl", reply, model, max_turns, budget, session))
    results = [c["result"] for c in calls]
    changed = sh(["git", "status", "--porcelain", "--untracked-files=all"], cwd=ws).stdout.splitlines()
    models_used: dict[str, float] = {}
    for r in results:
        for name, u in (r.get("modelUsage") or {}).items():
            models_used[name] = round(models_used.get(name, 0) + u.get("costUSD", 0), 3)
    summary = {
        "run_id": run_id, "task": task, "model": model, "skill": skill, "rep": rep, "natural": natural,
        "effort": EFFORT, "followups": followups, "exit_codes": [c["exit"] for c in calls],
        "wall_s": sum(c["wall_s"] for c in calls),
        "num_turns": sum(r.get("num_turns", 0) for r in results),
        "cost_usd": round(sum(r.get("total_cost_usd", 0) for r in results), 3),
        "output_tokens": sum((r.get("usage") or {}).get("output_tokens", 0) for r in results),
        "models_used": models_used, "stop_reasons": [r.get("subtype") for r in results],
        "deck_exists": find_deck(ws) is not None,
        "deck_path": str(find_deck(ws).relative_to(ws)) if find_deck(ws) else None,
        "changed_files": [c[3:] for c in changed],
        **summarize(run_dir),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("run_id", "followups", "num_turns", "wall_s", "cost_usd", "deck_exists",
                                              "stop_reasons", "skill_calls", "stop_hook_blocks", "rate_limits")},
                     ensure_ascii=False))


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["run"]:
        natural = "--natural" in args
        task, model, skill, rep = [a for a in args[1:] if not a.startswith("--")]
        run(task, model, skill, rep, natural)
    elif args[:1] == ["list"]:
        for s in sorted((WORK / "runs").glob("*/summary.json")):
            d = json.loads(s.read_text())
            print(f"{d['run_id']:28} turns={d['num_turns']:3} wall={d['wall_s']:5}s cost=${d['cost_usd']:6.2f} "
                  f"followups={d['followups']} deck={d['deck_exists']} blocks={d['stop_hook_blocks']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
