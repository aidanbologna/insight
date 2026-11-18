"""Shared set-up for the tests. They never touch the network or the real settings folder.

    python -m pytest web/tests
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# insight_core works out where the Windows app keeps its files when it is imported. Point that at a
# scratch folder here (inside Python, after it has found its own packages) so nothing real is in reach.
# (A test that starts a second Python has to hand it the real folder back: packages live under it.)
os.environ.setdefault("INSIGHT_REAL_APPDATA", os.environ.get("APPDATA", ""))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="insight-web-tests-")
