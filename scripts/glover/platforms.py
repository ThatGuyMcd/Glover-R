"""Rocket-R-compatible target selection; availability is reported separately."""
from __future__ import annotations
import re
ALL = ('Windows-x64', 'Linux-x86_64', 'Linux-aarch64', 'Android-arm64')
ALIASES = {
    '1': ALL[0], 'windows': ALL[0], 'win': ALL[0], 'windows-x64': ALL[0],
    '2': ALL[1], 'linux': ALL[1], 'linux-x64': ALL[1], 'linux-x86_64': ALL[1],
    '3': ALL[2], 'linux-arm64': ALL[2], 'linux-aarch64': ALL[2],
    '4': ALL[3], 'android': ALL[3], 'android-arm64': ALL[3],
}
def select(text: str | None) -> list[str]:
    result = []
    for raw in re.split(r'[,;\s]+', text.strip() if text and text.strip() else '1,2'):
        token = raw.lower()
        choices = ALL if token in ('a', 'all') else (ALIASES.get(token),)
        if None in choices:
            raise ValueError(f"Unknown platform choice {raw!r}; use 1,2,3,4 or A.")
        for value in choices:
            if value not in result:
                result.append(value)
    if ALL[0] in result and ALL[1] not in result:
        result.append(ALL[1])
    return result
