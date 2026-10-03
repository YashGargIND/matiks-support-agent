"""Matiks support workbench. Every external action is permanently dry-run."""

import os

# These must be set before any module imports the Agents SDK.
os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
os.environ["OPENAI_AGENTS_DONT_LOG_MODEL_DATA"] = "1"
os.environ["OPENAI_AGENTS_DONT_LOG_TOOL_DATA"] = "1"
