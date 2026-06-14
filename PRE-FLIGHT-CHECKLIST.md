# Kronos NSE Pre-Flight Checklist

## Environment
- [ ] `python3.11 --version` shows 3.11.x
- [ ] `node --version` shows v20.x
- [ ] `docker --version` works
- [ ] `uv --version` works
- [ ] `git --version` works

## Cursor
- [ ] Cursor 1.6+ installed
- [ ] Agent mode enabled
- [ ] Default model set to claude-sonnet-4-6
- [ ] Auto-run tools set to Ask before running

## MCP
- [ ] `~/.cursor/mcp.json` created from `.cursor/mcp.template.json`
- [ ] context7, github, postgres, redis, filesystem, memory, sequential-thinking, playwright, docker show green dots

## Rules
- [ ] `.cursor/rules/project-master.mdc`
- [ ] `.cursor/rules/python-fastapi.mdc`
- [ ] `.cursor/rules/dqg.mdc`
- [ ] `.cursor/rules/model-inference.mdc`
- [ ] `.cursor/rules/react-ui.mdc`
- [ ] `.cursor/rules/testing.mdc`

## Python
- [ ] `.venv` created with Python 3.11
- [ ] `uv pip install -e ".[dev]"` succeeds
- [ ] CUDA torch check returns available

## UI
- [ ] `ui/` initialized with Vite React+TS
- [ ] UI deps installed (lightweight-charts, tanstack query, zustand)

## Docker
- [ ] `docker compose up -d timescaledb redis` succeeds in `docker/`
- [ ] containers healthy
- [ ] postgres and redis connectivity checks pass

## Secrets and Git
- [ ] `.env` exists and not committed
- [ ] `.env.example` exists with placeholders
- [ ] `pre-commit install` completed
- [ ] initial git commit created and pushed
