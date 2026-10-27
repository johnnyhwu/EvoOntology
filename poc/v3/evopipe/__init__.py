"""evopipe — a deterministic, Python-controlled EvoOntology pipeline (PoC 2).

Control flow lives in Python. An LLM is only ever reached through ``evopipe.llm.LLM`` (one place),
whose backend is OpenRouter in production and ``claude -p`` as a stand-in while no API key is available.
The deterministic parts of EvoOntology (store, runtime, trajectories, trigger, gate, evolution session,
validation, rendering) are *imported from the repo's ``evoontology`` package*, not re-implemented.
"""
import os
import sys

sys.dont_write_bytecode = True

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
