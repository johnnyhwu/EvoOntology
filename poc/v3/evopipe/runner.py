"""Run many questions concurrently with on-disk caching (a re-run only executes what is missing)."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from . import config, use
from .llm import LLM


def run_questions(questions: List[Dict[str, str]], *, version: str, arm: str, out_dir: str,
                  workspace: str = config.WORKSPACE, stage: str = "use", concurrency: int = config.CONCURRENCY,
                  llm: LLM = None) -> Dict[str, Dict[str, Any]]:
    llm = llm or LLM("agent")
    os.makedirs(out_dir, exist_ok=True)

    def one(q):
        path = os.path.join(out_dir, q["id"] + ".json")
        if os.path.isfile(path):
            return q["id"], json.load(open(path, encoding="utf-8"))
        trajectory = use.run_task(question_id=q["id"], question=q["question"], workspace=workspace, version=version,
                                  arm=arm, llm=llm, stage=stage)
        use.save_run(path, trajectory)
        return q["id"], trajectory

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return dict(pool.map(one, questions))
