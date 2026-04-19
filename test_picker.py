"""Quick manual test for the session picker UI. Run directly in your terminal."""
from shad.sessions import _run_picker, OcSession

sessions = [
    OcSession(id="abc123", title="Fix authentication bug",      time_updated=1713500000000),
    OcSession(id="def456", title="New session - 2024-04-18T12:00:00Z", time_updated=1713400000000),
    OcSession(id="ghi789", title="Refactor database layer",     time_updated=1713300000000),
    OcSession(id="jkl012", title="Add rate limiting middleware", time_updated=1713200000000),
]

result = _run_picker(sessions, "shad")

if result is None:
    print("cancelled")
elif result == 0:
    print("chosen: + New session")
else:
    chosen = sessions[result - 1]
    print(f"chosen: {chosen.id}  —  {chosen.display_title}")
