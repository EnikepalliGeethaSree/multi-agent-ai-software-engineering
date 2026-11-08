"""Streaming loaders for the benchmarks in capstone-datasets/ (read-only)."""

from marl_agents.evaluation.datasets.bugsinpy import BugsInPySample, load_bugsinpy
from marl_agents.evaluation.datasets.codereviewer import (
    CodeReviewerSample,
    load_codereviewer,
    reservoir_sample,
    stream_codereviewer,
)

__all__ = [
    "BugsInPySample",
    "CodeReviewerSample",
    "load_bugsinpy",
    "load_codereviewer",
    "reservoir_sample",
    "stream_codereviewer",
]
