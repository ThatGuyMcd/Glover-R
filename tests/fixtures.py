"""Synthetic test data only. No retail ROM is bundled with the project."""
import copy
import hashlib
import json
from pathlib import Path
import struct
ROOT = Path(__file__).resolve().parents[1]

def fixture():
    profile = copy.deepcopy(json.loads((ROOT/'config/glover.us.json').read_text()))
    # 1 MiB synthetic image: not the 8 MiB target and never accepted by its hash.
    image = bytearray(0x100000)
    image[:4] = bytes.fromhex('80371240')
    struct.pack_into('>I', image, 8, profile['load_vram'])
    image[0x20:0x34] = b'SYNTHETIC TEST ROM'.ljust(20, b' ')
    image[0x3B:0x3F] = b'NGVE'
    words = [0x3C1D8026, 0x27BDF158, 0x3C08801F, 0x25085680,
             0x3C09802B, 0x25290D10, 0x11090005, 0, 0x25080004,
             0x0109082B, 0x1420FFFD, 0xAD00FFFC,
             0x0C000000 | ((profile['callable_entrypoint'] & 0x0FFFFFFF) >> 2),
             0, 0x0000000D, 0]
    struct.pack_into('>16I', image, profile['load_rom_offset'], *words)
    delta = profile['load_vram']-profile['load_rom_offset']
    function = profile['callable_entrypoint']-delta
    target = 0x8010C920
    struct.pack_into('>4I', image, function, 0x0C000000 | ((target & 0x0fffffff)>>2), 0, 0x03E00008, 0)
    struct.pack_into('>2I', image, target-delta, 0x03E00008, 0)
    canonical = bytes(image)
    profile['size'] = len(canonical)
    profile['sha1'] = hashlib.sha1(canonical).hexdigest()
    profile['sha256'] = hashlib.sha256(canonical).hexdigest()
    return canonical, profile

def swap16(data):
    result = bytearray(len(data)); result[0::2], result[1::2] = data[1::2], data[0::2]
    return bytes(result)

def swap32(data):
    result = bytearray(len(data))
    for i in range(4): result[i::4] = data[3-i::4]
    return bytes(result)


def scanner_source_fixture():
    """Reviewed n64sym hunk fixture, not a copy/build of the full scanner."""
    return '\n'*289+'''    default:
        for(auto& result : m_Results)
        {
            Output("%08X %s\\n", result.address, result.name);
        }
        break;
    }
'''+('\n'*550)+'''
    for(auto& otherResult : m_Results)
    {
        if(otherResult.address == result.address)
        {
            return false; // already have
        }
'''


def write_lf_fixture(path: Path, text: str) -> None:
    """Write deterministic UTF-8/LF test bytes without host newline translation.

    Path.write_text() with no newline argument creates CRLF on Windows. Git
    applies an LF patch to the fixture's bytes, not to read_text()'s normalized
    view. Use binary output so tests match the production LF dependency checkout.
    This helper is test-only and never rewrites a user's dependency or game C.
    """
    path.write_bytes(text.replace('\r\n', '\n').encode('utf-8'))
