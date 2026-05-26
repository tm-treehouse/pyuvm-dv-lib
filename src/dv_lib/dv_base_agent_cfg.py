# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_agent_cfg: Per-agent configuration object.

The original SV ``dv_base_agent_cfg`` is a ``uvm_object`` that holds the
common knobs every agent needs:

* ``if_mode``       — host/device direction the agent is configured to drive,
* ``is_active``     — UVM_ACTIVE / UVM_PASSIVE,
* ``en_cov``        — coverage on/off,
* ``en_monitor``    — whether the monitor is enabled at all,
* ``zero_delays``   — drive everything as fast as possible,
* a virtual interface handle (``vif``) supplied by the testbench via
  ``uvm_config_db``.

In pyuvm there is no ``uvm_object`` per se — a plain Python class works fine
and is what pyuvm's own examples use for cfg objects. We expose the same set
of knobs with the same names so that porting tests is mechanical.
"""
from __future__ import annotations

from enum import IntEnum
from typing import Any, Optional


class IfMode(IntEnum):
    """Agent direction. Mirrors ``dv_utils_pkg::if_mode_e``."""
    Host = 0      # drives the bus; equivalent to "host" / "master"
    Device = 1    # responds to the bus; equivalent to "device" / "slave"


# UVM activity enum — pyuvm exposes ``uvm_active_passive_enum`` with
# UVM_ACTIVE = 1 / UVM_PASSIVE = 0, but we keep our own to avoid forcing
# the import here and to allow plain ints in tests.
UVM_PASSIVE = 0
UVM_ACTIVE = 1


class DVBaseAgentCfg:
    """Configuration object shared between an agent's components.

    The real SV class is parametrized on the IP and adds IP-specific
    knobs; this Python base just covers the universal ones. Extend
    freely:

        class MyAgentCfg(DVBaseAgentCfg):
            def __init__(self):
                super().__init__()
                self.my_extra_knob = 0
    """

    def __init__(self, name: str = "dv_base_agent_cfg") -> None:
        self.name: str = name
        self.if_mode: IfMode = IfMode.Host
        self.is_active: int = UVM_ACTIVE
        self.en_cov: bool = True
        self.en_monitor: bool = True
        self.zero_delays: bool = False
        # Virtual-interface analogue. In SystemVerilog this is a typed
        # virtual interface handle; in Python it's whatever object the
        # testbench wires up (a cocotb handle, a stub, ...). We keep it
        # untyped on purpose — agent code uses duck typing.
        self.vif: Optional[Any] = None

    # Convenience predicate; matches the ``is_active`` check in
    # ``dv_base_agent::build_phase``.
    @property
    def active(self) -> bool:
        return self.is_active == UVM_ACTIVE

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"{type(self).__name__}(if_mode={self.if_mode.name}, "
            f"is_active={self.is_active}, en_cov={self.en_cov}, "
            f"en_monitor={self.en_monitor}, zero_delays={self.zero_delays})"
        )
