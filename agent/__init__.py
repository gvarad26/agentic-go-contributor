"""An agentic AI contributor for open-source Go projects.

The package turns a GitHub issue into a code change: it inspects the repository,
locates the relevant files, plans a fix, edits the code, runs Go checks, and
produces a pull-request title and body plus a patch.

See ``agent.pipeline`` for the high-level orchestration and ``agent.tools`` for
the tool surface exposed to the model.
"""

__version__ = "0.1.0"
