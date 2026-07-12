"""Legal Intelligence Collection Layer — Environment A production pipeline.

Paradigm (per ARCHITECTURE-SPINE.md): pipes-and-filters over a Notion blackboard.
Each pipeline stage is an idempotent filter that reads Items in one status and
writes them in the next; the Item ``status`` field is the only coordination pipe.
"""

__version__ = "0.0.0"
