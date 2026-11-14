"""Debug helper: type a line on a VM console with `virsh send-key` (evidence/debug only).

  PYTHONPATH=apps/api python tools/infra-validation/vm_type.py <domain> "<text>"
"""
import sys
import time

from app.deploy import vm

PLAIN = {" ": "KEY_SPACE", "-": "KEY_MINUS", ".": "KEY_DOT", "\\": "KEY_BACKSLASH", "/": "KEY_SLASH",
         ";": "KEY_SEMICOLON", "'": "KEY_APOSTROPHE", ",": "KEY_COMMA", "=": "KEY_EQUAL"}
SHIFTED = {":": "KEY_SEMICOLON", "_": "KEY_MINUS", "*": "KEY_8", "|": "KEY_BACKSLASH", '"': "KEY_APOSTROPHE",
           "$": "KEY_4", "(": "KEY_9", ")": "KEY_0", ">": "KEY_DOT", "?": "KEY_SLASH"}

domain, text = sys.argv[1], sys.argv[2]
for char in text:
    if char.isalpha():
        keys = (["KEY_LEFTSHIFT"] if char.isupper() else []) + [f"KEY_{char.upper()}"]
    elif char.isdigit():
        keys = [f"KEY_{char}"]
    elif char in PLAIN:
        keys = [PLAIN[char]]
    elif char in SHIFTED:
        keys = ["KEY_LEFTSHIFT", SHIFTED[char]]
    else:
        raise SystemExit(f"unsupported character {char!r}")
    vm.virsh(["send-key", domain, *keys])
    time.sleep(0.03)
vm.virsh(["send-key", domain, "KEY_ENTER"])
