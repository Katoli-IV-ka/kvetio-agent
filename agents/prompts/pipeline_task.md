# Routine Bootstrap Prompt - Kvetio Pipeline

You are running the Kvetio lead-generation pipeline inside a Claude Code Routine.

This prompt is intentionally stable and should rarely change. The real pipeline
instructions live in the repository so the agent can be changed by Git commits
instead of editing the hosted Routine prompt.

At the beginning of every run:

1. Read the repository-managed prompt:
   ```bash
   cat agents/prompts/pipeline_main_task.md
   ```
2. Treat `agents/prompts/pipeline_main_task.md` as the authoritative runtime
   instruction for this run.
3. Preserve the Routine `/fire` `text` payload exactly as the runtime parameter
   string. The main prompt explains how to parse and apply it.
4. Follow the repository-managed prompt, not stale pipeline instructions that may
   have been copied into the Routine in the past.

If `agents/prompts/pipeline_main_task.md` cannot be read, stop the pipeline and
send an error notification:

```bash
python scripts/notify.py --error '{"task":"pipeline_bootstrap","error":"agents/prompts/pipeline_main_task.md not found or unreadable"}'
```
