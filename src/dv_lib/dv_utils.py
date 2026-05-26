# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_utils: Plusarg helpers and small utilities.

SystemVerilog's ``$value$plusargs("name=%0d", var)`` is used heavily in
``dv_base_test`` and friends to let ``dvsim`` flip knobs on the command line
(``+en_scb=1``, ``+UVM_TEST_SEQ=foo_smoke_vseq``, ...).

Under cocotb the equivalent is :data:`cocotb.plusargs` — a dict that cocotb
populates from the simulator command line (``+name=value`` -> ``{"name":
"value"}``; a bare ``+flag`` -> ``{"flag": True}``). That is the *authoritative*
source when a simulation is live, so these helpers read from it first.

Resolution order for a plusarg lookup:

1. **cocotb.plusargs** — the real simulator plusargs. When a sim is
   running these ALWAYS win, so a ``+arg`` on the simulator command
   line can never be masked by a Python-side override.
2. **Explicit overrides** set via :func:`set_plusargs` — used by unit
   tests, and as a programmatic default when no simulator supplied the
   plusarg.
3. **PYUVM_PLUSARGS** environment variable (``+a=1 +b=foo`` style) — a
   convenience for running the library outside a simulator (plain
   pytest). Loaded into the same store as the explicit overrides.

Calling code in the rest of the library mirrors the SystemVerilog pattern:

    cfg.en_scb = plusarg_bool("en_scb", cfg.en_scb)

which is the moral equivalent of

    void'($value$plusargs("en_scb=%0b", cfg.en_scb));
"""
from __future__ import annotations

import os
import shlex
from typing import Dict, Optional, Union

import cocotb


# Explicit overrides (tests) and the env-var fallback live here. cocotb's
# own ``cocotb.plusargs`` is consulted directly at lookup time and is NOT
# copied in, so it always reflects the live simulator.
_PLUSARGS: Dict[str, str] = {}


def _parse_plusarg_string(text: str) -> Dict[str, str]:
    """Parse a ``+a=1 +b=foo +flag`` style string into a dict."""
    out: Dict[str, str] = {}
    for token in shlex.split(text):
        if not token.startswith("+"):
            continue
        token = token[1:]
        if "=" in token:
            key, _, value = token.partition("=")
            out[key] = value
        else:
            # bare flag, e.g. `+verbose`
            out[token] = "1"
    return out


def _load_from_env() -> None:
    """Populate _PLUSARGS from the PYUVM_PLUSARGS environment variable, once."""
    raw = os.environ.get("PYUVM_PLUSARGS")
    if raw:
        _PLUSARGS.update(_parse_plusarg_string(raw))


_load_from_env()


def set_plusargs(**kwargs: object) -> None:
    """Install plusargs from Python (mostly used by tests).

    These apply only when the live simulator did not supply the same
    plusarg: ``cocotb.plusargs`` always takes precedence, so a real
    ``+arg`` on the simulator command line is never masked by a
    Python-side override.
    """
    for k, v in kwargs.items():
        _PLUSARGS[k] = str(v)


def clear_plusargs() -> None:
    """Drop every *explicit* plusarg override. Does not touch
    ``cocotb.plusargs`` (that belongs to the simulator). Useful between
    test cases.
    """
    _PLUSARGS.clear()


def _cocotb_plusargs() -> Dict[str, Union[str, bool]]:
    """Return cocotb's plusargs dict, or empty if no sim is live.

    ``cocotb.plusargs`` only exists once cocotb has processed the
    simulator command line, so we access it defensively.
    """
    return getattr(cocotb, "plusargs", None) or {}


def _normalize(value: Union[str, bool]) -> str:
    """Coerce a cocotb plusarg value to a string.

    cocotb stores a bare ``+flag`` as ``True``; we represent that as
    ``"1"`` so the bool/int parsers treat it as set-and-true.
    """
    if value is True:
        return "1"
    if value is False:
        return "0"
    return str(value)


def _get(name: str) -> Optional[str]:
    """Resolve a plusarg by name following the documented precedence:
    the live simulator's plusargs first, then explicit overrides, then
    the env-var fallback.
    """
    # 1. The live simulator's plusargs ALWAYS win. A real +arg on the
    #    simulator command line can never be masked by a Python-side
    #    override.
    cargs = _cocotb_plusargs()
    if name in cargs:
        return _normalize(cargs[name])
    # 2. Explicit overrides (set_plusargs) and anything loaded from
    #    PYUVM_PLUSARGS at import time both live in _PLUSARGS. These
    #    only apply when the simulator did not supply the plusarg —
    #    typically the no-simulator / pytest path.
    if name in _PLUSARGS:
        return _PLUSARGS[name]
    return None


def plusarg_int(name: str, default: int) -> int:
    """Look up an integer plusarg, falling back to ``default`` when unset."""
    raw = _get(name)
    if raw is None:
        return default
    try:
        # accept decimal, hex, binary, etc.
        return int(raw, 0) if isinstance(raw, str) else int(raw)
    except (TypeError, ValueError):
        return default


def plusarg_bool(name: str, default: bool) -> bool:
    """Look up a boolean plusarg.

    Accepts ``1/0``, ``true/false``, ``yes/no`` (case-insensitive), and a
    bare cocotb flag (stored as ``True`` -> ``"1"``). Anything else falls
    back to ``default``.
    """
    raw = _get(name)
    if raw is None:
        return default
    raw_lower = raw.strip().lower()
    if raw_lower in ("1", "true", "yes", "y", "on"):
        return True
    if raw_lower in ("0", "false", "no", "n", "off"):
        return False
    return default


def plusarg_str(name: str, default: str) -> str:
    """Look up a string plusarg, falling back to ``default`` when unset."""
    raw = _get(name)
    return default if raw is None else raw
