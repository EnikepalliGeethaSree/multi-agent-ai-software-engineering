"""FastAPI backend + dashboard hosting: thin routes over the agents and review jobs."""

from marl_agents.api.app import create_app
from marl_agents.api.jobs import JobInfo, JobManager, JobStatus, ReviewOptions

__all__ = ["JobInfo", "JobManager", "JobStatus", "ReviewOptions", "create_app"]
