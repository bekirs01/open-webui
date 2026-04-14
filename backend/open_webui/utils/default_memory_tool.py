"""
Seed the bundled `memory` user-storage tool into the database (idempotent).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from open_webui.models.tools import ToolForm, ToolMeta, Tools
from open_webui.models.users import Users
from open_webui.utils.plugin import load_tool_module_by_id, replace_imports
from open_webui.utils.tools import get_tool_specs

log = logging.getLogger(__name__)

_PUBLIC_READ = [{'principal_type': 'user', 'principal_id': '*', 'permission': 'read'}]
_MEMORY_TOOL_ID = 'memory'


def seed_default_memory_tool() -> None:
    """Insert tool `memory` from default_tools/memory.py if missing."""
    try:
        if Tools.get_tool_by_id(_MEMORY_TOOL_ID):
            return

        owner = Users.get_super_admin_user() or Users.get_first_user()
        if not owner:
            log.debug('default memory tool: no user yet, skip seeding')
            return

        path = Path(__file__).resolve().parent.parent / 'default_tools' / 'memory.py'
        content = path.read_text(encoding='utf-8')
        content = replace_imports(content)

        tool_module, frontmatter = load_tool_module_by_id(_MEMORY_TOOL_ID, content=content)
        try:
            specs = get_tool_specs(tool_module)
        finally:
            sys.modules.pop(f'tool_{_MEMORY_TOOL_ID}', None)

        form = ToolForm(
            id=_MEMORY_TOOL_ID,
            name='memory',
            content=content,
            meta=ToolMeta(
                description='Persistent per-user file storage and workspace tools (memory).',
                manifest=frontmatter or {},
            ),
            access_grants=_PUBLIC_READ,
        )
        created = Tools.insert_new_tool(owner.id, form, specs)
        if created:
            log.info('Default tool `memory` seeded (shared read access)')
        else:
            log.warning('Default tool `memory` seed failed (insert returned none)')
    except Exception as e:
        log.warning('default memory tool seed failed: %s', e)
