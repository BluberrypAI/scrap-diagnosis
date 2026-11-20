@AGENTS.md

## Claude Code 전용

- `.claude/worktrees/`는 서브에이전트 작업 공간이다. 커밋하지 않고 ruff 검사에서도 뺀다(`pyproject.toml`의 `extend-exclude`)
- 서브에이전트에게 맡긴 작업도 AGENTS.md 5장의 검증을 통과해야 병합한다
- 실제 AI(Azure)를 부르는 평가(`tools/eval_understand.py`를 `--mock`·`--oracle` 없이 실행)는 비용이 드므로 사용자가 요청하거나 프롬프트·추출 로직을 바꿨을 때만 실행한다
