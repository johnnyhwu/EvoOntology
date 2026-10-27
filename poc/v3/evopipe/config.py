"""All paths, model roles and knobs in one place (edit here when you re-implement)."""
import os

V3 = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POC = os.path.abspath(os.path.join(V3, ".."))
REPO = os.path.abspath(os.path.join(POC, ".."))

# ---- inputs carried over from PoC 1 (same scenario: Lumo Outdoors) --------------------------
DB_PATH = os.path.join(POC, "data", "shop_v2.sqlite")
DOC_PATH = os.path.join(POC, "build_input_v2", "domain_knowledge.md")
CONSTRUCTION_Q = os.path.join(POC, "build_input_v2", "construction_questions.json")

# ---- inputs generated for PoC 2 -----------------------------------------------------------
STREAM_Q = os.path.join(V3, "scenario", "stream_questions.json")
TEST_Q = os.path.join(V3, "scenario", "test_questions.json")
GT_PATH = os.path.join(V3, "_private", "gt.json")     # read ONLY by audit.py

# ---- outputs ------------------------------------------------------------------------------
WORKSPACE = os.path.join(V3, "workspace", ".evoontology")
RUNS = os.path.join(V3, "runs")
# Neutral cwd for `claude -p`. MUST be outside the git repo: Claude Code keys its project memory by git root, so a cwd inside the repo
# leaks MEMORY.md into every call (found by the PoC-2 audit; CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 did NOT prevent it).
import tempfile
LLM_CWD = os.path.join(tempfile.gettempdir(), "evopipe_llm_cwd")

# ---- the repo's own skill/reference texts are fed to the LLM verbatim -----------------------
SKILLS = os.path.join(REPO, "plugins", "claude-code", "skills")
BUILD_SKILL = os.path.join(SKILLS, "build-ontology", "SKILL.md")
EVOLVE_SKILL = os.path.join(SKILLS, "evolve-ontology", "SKILL.md")
SCHEMA_MD = os.path.join(SKILLS, "build-ontology", "references", "ontology-schema.md")
PROTOCOL_MD = os.path.join(SKILLS, "build-ontology", "references", "ontology-interaction-protocol.md")
BOUNDARY_MD = os.path.join(SKILLS, "build-ontology", "references", "ontology-layer-data-boundary.md")
EXPLORATION_MD = os.path.join(SKILLS, "evolve-ontology", "references", "exploration-guide.md")

# ---- LLM backend & roles ------------------------------------------------------------------
BACKEND = os.environ.get("EVOPIPE_BACKEND", "claude_cli")      # claude_cli | openrouter | mock
BUDGET_USD = float(os.environ.get("EVOPIPE_BUDGET_USD", "7.5"))

# role -> model.  Roles are what the pipeline asks for; models are what a backend serves.
ROLE_MODELS = {
    "builder": "claude-sonnet-5-5",   # semantic design (needs strength)
    "agent":   "claude-sonnet-5-5",   # the Data Agent.  Use stage + gate round 1/2 (first repetition) ran with claude-haiku-5-5; see report
    "evolver": "claude-sonnet-5-5",   # diagnose / attribute / patch
    "judge":   "claude-sonnet-5-5",   # separate instance & context from the Evolver. Earlier gate repetitions used claude-opus-5-5; see report
}
# What the same roles would be on OpenRouter (open-source models). Not exercised in this PoC
# (no API key) — see report §"OpenRouter backend".
OPENROUTER_ROLE_MODELS = {
    "builder": "qwen/qwen3-235b-a22b-2507",
    "agent":   "qwen/qwen3-30b-a3b-instruct-2507",
    "evolver": "qwen/qwen3-235b-a22b-2507",
    "judge":   "deepseek/deepseek-chat-v3.1",
}
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
ENV_FILE = os.path.join(POC, ".env")                           # OPENROUTER_API_KEY=... (never committed)

# ---- data-agent / tools -------------------------------------------------------------------
AGENT_MAX_STEPS = 10
SQL_MAX_ROWS = 50                 # rows shown to the model
SQL_STEP_LIMIT = 60_000_000       # sqlite VM steps (core uses ~1M; that truncated Build queries in PoC 1)
TOOL_RESULT_CHARS_FOR_MODEL = 3500
CONCURRENCY = int(os.environ.get("EVOPIPE_CONCURRENCY", "6"))

# ---- evolution ----------------------------------------------------------------------------
MAX_ROUNDS = 2                    # core default is 8 ("full"); 2 is the "quick" profile. Bounded by the US$5 cost cap.
POOL_FRACTION = 0.7               # data-boundary doc: default 70% Evolution Pool / 30% Validation Reserve
NEAR_DUP_JACCARD = 0.85
