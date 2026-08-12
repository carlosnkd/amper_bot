"""
Shared LLM factory used by every agent pipeline in this repo.

Pulled out of agents/research/agent.py so new pipelines (e.g. ticket_pipeline)
don't duplicate the credential-loading boilerplate.

Uses Claude (Anthropic) directly -- crewai routes any "claude-*" model string
to its native Anthropic provider (crewai.llms.providers.anthropic.completion),
which wraps the official `anthropic` SDK. Requires ANTHROPIC_API_KEY to be set
(env var or .env file); no Vertex/GCP credentials needed.

Note: Claude Opus 5 rejects non-default temperature/top_p/top_k (400 error) --
sampling params were removed on this model tier, so don't add temperature=...
back here without checking shared/model-migration.md first.

max_tokens is raised well above crewai's AnthropicCompletion default (4096)
because Claude Opus 5 thinks by default and thinking + response share that
same budget -- at 4096 the Coder's file-writing tool calls can get cut off
mid-output. stream=True goes with it: the Anthropic SDK risks an HTTP
timeout on large non-streaming max_tokens.

`llm` (Opus) is for work that benefits from Opus-tier reasoning: actual code
generation (coder_agent). `structured_llm` (Sonnet) is for agents whose job
is a constrained, deterministic JSON output rather than open-ended reasoning
-- planner_agent and reviewer_agent -- mirroring why Intent
(backend/services/bot/intent.py) already runs its own classification on
Haiku instead of Opus. Sonnet doesn't think by default the way Opus 5 does,
so this also drops the implicit reasoning-token tax on every Planner/Reviewer
call, on top of the per-token price difference. Same max_tokens/stream
reasoning applies (Planner/Reviewer's JSON output can be long enough to want
the same headroom).
"""

from crewai import LLM
from dotenv import load_dotenv

load_dotenv()

llm = LLM(model="anthropic/claude-opus-5", max_tokens=16000, stream=True)
structured_llm = LLM(model="anthropic/claude-sonnet-5", max_tokens=16000, stream=True)
