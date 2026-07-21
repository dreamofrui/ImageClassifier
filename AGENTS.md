# Repository Guidelines

## Project Overview

ARS is a small Windows-oriented Python desktop toolkit. The current app is a
Tkinter image classifier that previews images and moves them into target
folders based on keyboard bindings.

Core files:

- `main.py`: Tkinter launcher for the ARS toolkit.
- `image_classifier.py`: main image classification UI and file-moving logic.
- `shortcut_manager.py`: shortcut configuration, migration, validation, and
  Tk event binding.
- `binding_profiles.py`: reusable classification key binding profile migration
  and normalization.
- `config_manager.py`: JSON config loading/saving and PyInstaller-aware app
  directory lookup.
- `config.json`: runtime configuration for supported formats, key bindings,
  binding profiles, shortcuts, window size, and zoom behavior.
- `ImageClassifier.spec` and `build.bat`: PyInstaller packaging entry points.
- `docs/`: design notes and API/reference documentation.

## 环境

- 唯一 Python 解释器：`D:/miniforge3/envs/tool/python.exe`

## Subagents

- Subagents may be used when work can be split into independent, non-conflicting file scopes.
- The owner has explicitly authorized using subagents for implementation help, review, and boundary/spec checks.
- The current owner-approved upper limit is six concurrent subagents.
- Give each subagent enough project context, owned files, constraints, and expected verification so they can work without guessing.
- Prefer subagents for review, spec-boundary checks, UI critique, and isolated implementation slices.
- Do not assign two subagents to edit the same files at the same time.
- The lead agent remains responsible for integration, final verification, and resolving conflicts.

## 先看哪些文件

1. `docs/PROJECT_PROGRESS.md`
2. `docs/ARCHITECTURE_REVIEW.md`
3. `README.md`
4. `USER_GUIDE.md`

如果准备新增功能、改接口或补测试，再看：

- `docs/DEVELOPMENT_GUIDE.md`

## Behavioral Guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### Binding Profiles

- Classification key profiles live in `config.json` under
  `image_classifier.binding_profiles`.
- `image_classifier.active_binding_profile` names the profile currently selected
  in the UI.
- Keep `image_classifier.default_key_bindings` synchronized with the active
  profile for backward compatibility.

### Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" -> "Write tests for invalid inputs, then make them pass"
- "Fix the bug" -> "Write a test that reproduces it, then make it pass"
- "Refactor X" -> "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **ARS** (795 symbols, 1728 relationships, 69 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/ARS/context` | Codebase overview, check index freshness |
| `gitnexus://repo/ARS/clusters` | All functional areas |
| `gitnexus://repo/ARS/processes` | All execution flows |
| `gitnexus://repo/ARS/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
