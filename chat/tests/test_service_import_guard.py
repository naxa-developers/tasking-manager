"""RagService must stay importable when the retrieval stack is broken.

The import guard in ``chat/service.py`` is what keeps a broken RAG dependency
from taking the whole API down; the module-level re-exports the API layer and
external callers rely on must survive that state.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_PROBE = """
import sys

# Any chat.retrieval import from here on fails, tripping the service guard.
sys.modules["chat.retrieval"] = None
import chat.service as service

assert service._RAG_AVAILABLE is False, "retrieval guard should trip"
assert service.RagAnswerFailed
assert service.MAX_ROUTING_HISTORY == 10
print("guard-ok")
"""


def test_service_import_survives_broken_retrieval():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "guard-ok" in result.stdout
