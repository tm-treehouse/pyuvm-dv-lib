# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_lib: A pyuvm port of the OpenTitan dv_lib SystemVerilog UVM base library.

Original SystemVerilog source:
    https://github.com/lowRISC/opentitan/tree/master/hw/dv/sv/dv_lib

The original dv_lib is a thin layer of base classes that every OpenTitan
testbench builds on. The classes provide common knobs (en_scb, en_cov,
zero_delays, smoke_test, ...), a shared report server / catcher, plusarg
plumbing and a standard build/connect skeleton, so individual IP testbenches
only have to fill in the IP-specific pieces.

This Python port keeps the same class names, the same inheritance shape, and
the same role for each class, so that an engineer familiar with the original
SystemVerilog code can navigate it. Where SystemVerilog idioms have no direct
pyuvm equivalent (parameterized classes, RAL, virtual interfaces, plusargs,
$value$plusargs, the report server) we pick the closest pyuvm idiom and call
out the difference in the docstring.
"""

from .dv_base_seq_item import DVBaseSeqItem
from .dv_base_agent_cfg import DVBaseAgentCfg, IfMode, UVM_ACTIVE, UVM_PASSIVE
from .dv_base_agent_cov import DVBaseAgentCov
from .dv_base_monitor import DVBaseMonitor
from .dv_base_driver import DVBaseDriver
from .dv_base_sequencer import DVBaseSequencer
from .dv_base_sequence import DVBaseSequence
from .dv_base_agent import DVBaseAgent
from .dv_base_reg_block import (
    DVBaseRegField,
    DVBaseReg,
    DVBaseRegBlock,
)
from .dv_base_env_cfg import DVBaseEnvCfg
from .dv_base_env_cov import DVBaseEnvCov
from .dv_base_virtual_sequencer import DVBaseVirtualSequencer
from .dv_base_scoreboard import DVBaseScoreboard
from .dv_base_env import DVBaseEnv
from .dv_base_vseq import DVBaseVSeq
from .dv_base_test import DVBaseTest
from .dv_report import DVReportCatcher, install_dv_report_server
from .dv_clk_rst import ClkRstIf
from .dv_utils import (
    plusarg_int,
    plusarg_bool,
    plusarg_str,
    set_plusargs,
    clear_plusargs,
)

__all__ = [
    "DVBaseSeqItem",
    "DVBaseAgentCfg",
    "IfMode",
    "UVM_ACTIVE",
    "UVM_PASSIVE",
    "DVBaseAgentCov",
    "DVBaseMonitor",
    "DVBaseDriver",
    "DVBaseSequencer",
    "DVBaseSequence",
    "DVBaseAgent",
    "DVBaseRegField",
    "DVBaseReg",
    "DVBaseRegBlock",
    "DVBaseEnvCfg",
    "DVBaseEnvCov",
    "DVBaseVirtualSequencer",
    "DVBaseScoreboard",
    "DVBaseEnv",
    "DVBaseVSeq",
    "DVBaseTest",
    "DVReportCatcher",
    "install_dv_report_server",
    "ClkRstIf",
    "plusarg_int",
    "plusarg_bool",
    "plusarg_str",
    "set_plusargs",
    "clear_plusargs",
]
