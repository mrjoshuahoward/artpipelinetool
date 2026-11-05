"""Parallel subagents claiming at once must never receive the same asset."""
from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

from artpipeline.pipeline import Pipeline
from artpipeline.store import Store
from conftest import make_manifest, write_brief


def _worker(root: str, agent: str, q) -> None:
    p = Pipeline(Store.open(Path(root)))
    got = []
    for _ in range(3):
        got += [a["asset_id"] for a in p.claim(agent, n=1)["claimed"]]
    q.put(got)


def test_parallel_claims_are_exclusive(tmp_path):
    m = make_manifest(n_assets=40, heroes=0)
    m["settings"]["gate_threshold"] = 100
    Pipeline.init(write_brief(tmp_path / "brief.md", m))
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_worker, args=(str(tmp_path), f"sub-{i}", q)) for i in range(8)]
    for pr in procs:
        pr.start()
    results = [q.get(timeout=60) for _ in procs]
    for pr in procs:
        pr.join(timeout=60)
    claimed = [a for r in results for a in r]
    assert len(claimed) == 24
    assert len(set(claimed)) == 24
