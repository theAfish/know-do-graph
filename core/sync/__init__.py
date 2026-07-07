"""Remote-source sync subsystem.

Mirrors upstream files (SKILL.md, scripts, ...) into entry bodies without
needing an LLM. See :mod:`core.sync.remote_sync` for the public API.
"""

from core.sync.autolink import (  # noqa: F401
    AutoLinkResult,
    auto_link_entry,
    build_alias_index,
    find_mentions,
    parse_frontmatter,
)
from core.sync.remote_sync import (  # noqa: F401
    SyncResult,
    parse_github_url,
    run_periodic_sync,
    sync_all_due,
    sync_entry,
)
