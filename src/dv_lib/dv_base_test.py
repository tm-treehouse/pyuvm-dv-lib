# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_test: Direct port of ``hw/dv/sv/dv_lib/dv_base_test.sv``.

This file follows the original SystemVerilog as closely as the host
language allows. The SV source is reproduced as a comment near each
ported block so the mapping is easy to verify.

The big-picture mapping:

* SV type parameters ``CFG_T`` and ``ENV_T`` become Python class
  attributes ``cfg_type`` and ``env_type``.
* SV ``$value$plusargs`` becomes :func:`dv_lib.dv_utils.plusarg_*`,
  which read from :data:`cocotb.plusargs` (the simulator command line)
  when a sim is live, and from explicit/env overrides otherwise.
* SV's report-server / catcher hookup becomes a single call to
  :func:`dv_lib.dv_report.install_dv_report_server`.
* SV's ``DV_CHECK_RANDOMIZE_FATAL(cfg)`` becomes a call to the cfg's
  ``randomize`` hook with a fatal log on failure.
* SV's ``uvm_top.set_timeout(test_timeout_ns)`` becomes cocotb's
  :func:`cocotb.triggers.with_timeout` around the test sequence.
* SV's ``phase.phase_done.set_drain_time(drain_time_ns)`` becomes a
  real ``await Timer(drain_time_ns, "ns")`` after the sequence.
* SV's ``dv_utils_pkg::poll_for_stop`` becomes a background cocotb
  coroutine that polls at the requested interval with ``Timer``.
* SV's ``set_max_quit_count`` has no cocotb equivalent (cocotb fails
  the test on the first error/exception), so it is stored for
  inspection only.
* SV's ``phase.raise_objection`` / ``drop_objection`` is implicit in
  pyuvm — ``run_phase`` returning ends the run — so the body of
  ``run_seq`` reduces to ``await test_seq.start(...)``.

cocotb vs. no-cocotb: every cocotb-specific call below is guarded by
``cocotb.is_simulation``. Under a live simulator we use the real
cocotb primitives (``Timer``, ``with_timeout``, sim-time logging);
under plain pytest (no simulator) we degrade to plain-Python
behaviour so the library and its unit tests still run.
"""
from __future__ import annotations

import logging
from typing import Optional, Type

from pyuvm import uvm_test, ConfigDB

import cocotb
from cocotb.triggers import Timer, with_timeout, SimTimeoutError

from .dv_base_env import DVBaseEnv
from .dv_base_env_cfg import DVBaseEnvCfg
from .dv_base_sequence import DVBaseSequence
from .dv_base_vseq import DVBaseVSeq
from .dv_report import DVReportCatcher, install_dv_report_server
from .dv_utils import plusarg_bool, plusarg_int, plusarg_str


# Side-car stdlib logger, used only as a fallback when no simulator is
# live (e.g. unit tests under plain pytest). Under cocotb we prefer
# ``self.logger`` so messages carry simulation time — see ``_log``.
_dv_logger = logging.getLogger("dv_lib")


class DVBaseTest(uvm_test):
    """Direct port of the SV ``dv_base_test`` class.

    Subclass and override ``cfg_type`` / ``env_type`` (mirroring
    ``CFG_T`` / ``ENV_T``)::

        class MyTest(DVBaseTest):
            cfg_type = MyEnvCfg
            env_type = MyEnv
    """

    # SV: class dv_base_test #(type CFG_T = dv_base_env_cfg,
    #                          type ENV_T = dv_base_env) extends uvm_test;
    cfg_type: Type[DVBaseEnvCfg] = DVBaseEnvCfg
    env_type: Type[DVBaseEnv] = DVBaseEnv

    def __init__(self, name: str = "dv_base_test", parent=None) -> None:
        super().__init__(name, parent)

        # SV:
        #   ENV_T  env;
        #   CFG_T  cfg;
        #   bit    run_test_seq = 1'b1;
        #   string test_seq_s;
        self.env: Optional[DVBaseEnv] = None
        self.cfg: Optional[DVBaseEnvCfg] = None
        self.run_test_seq: bool = True
        self.test_seq_s: str = ""

        # SV:
        #   uint   max_quit_count  = 1;
        #   uint64 test_timeout_ns = 200_000_000; // 200ms
        #   uint   drain_time_ns   = 2_000;       // 2us
        #   bit    poll_for_stop   = 1'b0;
        #   uint   poll_for_stop_interval_ns = 1000;
        #   bit    print_topology  = 1'b0;
        self.max_quit_count: int = 1
        self.test_timeout_ns: int = 200_000_000
        self.drain_time_ns: int = 2_000
        self.poll_for_stop: bool = False
        self.poll_for_stop_interval_ns: int = 1000
        self.print_topology: bool = False

        # The report catcher we install in build_phase. Stored on self
        # so the test can introspect it / add more rules later.
        self.report_catcher: Optional[DVReportCatcher] = None

        # Background poll_for_stop task handle (cocotb), if started.
        self._poll_task = None
        # Set True via request_stop() to end the test early.
        self._stop_requested: bool = False

    # ------------------------------------------------------------------
    # _log — choose the right logger. Under a live simulator we use
    # pyuvm's ``self.logger`` so records carry simulation time; under
    # plain pytest we use the side-car stdlib logger to avoid cocotb's
    # sim-time log filter (which needs a running simulator).
    # ------------------------------------------------------------------
    @property
    def _log(self) -> logging.Logger:
        if cocotb.is_simulation:
            return self.logger
        return _dv_logger

    # ------------------------------------------------------------------
    # build_phase — direct port of dv_base_test::build_phase.
    # ------------------------------------------------------------------
    def build_phase(self) -> None:
        # SV:
        #   dv_report_server  m_dv_report_server = new();
        #   dv_report_catcher m_report_catcher;
        #   uvm_report_server::set_server(m_dv_report_server);
        #   `uvm_create_obj(dv_report_catcher, m_report_catcher)
        #   add_message_demotes(m_report_catcher);
        #   uvm_report_cb::add(null, m_report_catcher);
        #
        # Important ordering note for pyuvm: pyuvm gives each component
        # its own logger with propagate=False and its own handler. That
        # means the install has to walk DOWN into every component's
        # logger to attach the catcher, and those loggers only exist
        # after components have been constructed. We therefore split
        # the SV-equivalent step into two halves:
        #   - here in build_phase: construct the catcher and let the
        #     subclass populate its rules via add_message_demotes;
        #   - in end_of_elaboration_phase below: walk the now-complete
        #     logger tree and attach the catcher to every component's
        #     handler.
        self.report_catcher = DVReportCatcher()
        self.add_message_demotes(self.report_catcher)

        super().build_phase()

        # SV:
        #   env = ENV_T::type_id::create("env", this);
        self.env = self.env_type.create("env", self)

        # SV:
        #   if (!uvm_config_db#(CFG_T)::get(this, "env", "cfg", cfg)) begin
        #       base_cfg = cfg_type.create_object("cfg");
        #       ...
        #       cfg.initialize();
        #   end
        try:
            self.cfg = ConfigDB().get(self, "env", "cfg")
        except Exception:
            self.cfg = self.cfg_type()
            self.cfg.initialize()

        # SV: `DV_CHECK_RANDOMIZE_FATAL(cfg)
        if not self.cfg.randomize():
            self._log.critical("Failed to randomize cfg object")

        # SV: uvm_config_db#(CFG_T)::set(this, "env", "cfg", cfg);
        ConfigDB().set(self, "env", "cfg", self.cfg)

        # SV: void'($value$plusargs("en_scb=%0b", cfg.en_scb));
        self.cfg.en_scb = plusarg_bool("en_scb", self.cfg.en_scb)
        # SV: void'($value$plusargs("en_scb_mem_chk=%0b", cfg.en_scb_mem_chk));
        self.cfg.en_scb_mem_chk = plusarg_bool("en_scb_mem_chk",
                                               self.cfg.en_scb_mem_chk)
        # SV: void'($value$plusargs("zero_delays=%0b", cfg.zero_delays));
        self.cfg.zero_delays = plusarg_bool("zero_delays", self.cfg.zero_delays)
        # SV: void'($value$plusargs("en_cov=%0b", cfg.en_cov));
        self.cfg.en_cov = plusarg_bool("en_cov", self.cfg.en_cov)
        # SV: void'($value$plusargs("smoke_test=%0b", cfg.smoke_test));
        self.cfg.smoke_test = plusarg_bool("smoke_test", self.cfg.smoke_test)
        # SV: void'($value$plusargs("print_topology=%0b", print_topology));
        self.print_topology = plusarg_bool("print_topology", self.print_topology)

        # SV: uvm_top.enable_print_topology = print_topology;
        # pyuvm has no global ``enable_print_topology`` knob; we emit a
        # debug log if the user asked for one. The framework's own
        # ``uvm_root.run`` already prints the hierarchy.
        if self.print_topology:
            self._log.info("print_topology=1 (handled at run time)")

        # SV: void'($value$plusargs("cdc_instrumentation_enabled=%d", cfg.en_dv_cdc));
        self.cfg.en_dv_cdc = plusarg_int("cdc_instrumentation_enabled",
                                         self.cfg.en_dv_cdc)

        # SV: uvm_config_db#(CFG_T)::set(this, "*", "cfg", cfg);
        ConfigDB().set(self, "*", "cfg", self.cfg)

    # ------------------------------------------------------------------
    # end_of_elaboration_phase
    # ------------------------------------------------------------------
    def end_of_elaboration_phase(self) -> None:
        super().end_of_elaboration_phase()

        # Now that every component has been constructed, walk the
        # logger tree and attach the catcher to each component's
        # handler. Doing this here (rather than in build_phase) is
        # what makes the catcher actually see records from pyuvm
        # components whose loggers don't propagate. See the
        # ``install_dv_report_server`` docstring for the why.
        if self.report_catcher is not None:
            install_dv_report_server(self.report_catcher)

        # SV:
        #   void'($value$plusargs("max_quit_count=%0d", max_quit_count));
        #   set_max_quit_count(max_quit_count);
        self.max_quit_count = plusarg_int("max_quit_count", self.max_quit_count)
        # No equivalent in pyuvm — store the value for inspection.

        # SV:
        #   void'($value$plusargs("test_timeout_ns=%0d", test_timeout_ns));
        #   uvm_top.set_timeout((test_timeout_ns * 1ns));
        self.test_timeout_ns = plusarg_int("test_timeout_ns",
                                           self.test_timeout_ns)
        # The value is read here; it is *enforced* in run_phase by
        # wrapping the test sequence in cocotb's ``with_timeout`` (see
        # below). cocotb has no global "set the timeout once" call, so
        # the timeout is applied at the point the sequence runs.

    # ------------------------------------------------------------------
    # run_phase — direct port of dv_base_test::run_phase.
    # ------------------------------------------------------------------
    async def run_phase(self) -> None:
        # SV:
        #   void'($value$plusargs("drain_time_ns=%0d", drain_time_ns));
        #   phase.phase_done.set_drain_time(this, (drain_time_ns * 1ns));
        self.drain_time_ns = plusarg_int("drain_time_ns", self.drain_time_ns)
        # Enforced after the sequence completes — see the Timer below.

        # SV:
        #   void'($value$plusargs("poll_for_stop=%0b", poll_for_stop));
        #   void'($value$plusargs("poll_for_stop_interval_ns=%0d",
        #                          poll_for_stop_interval_ns));
        #   if (poll_for_stop)
        #       dv_utils_pkg::poll_for_stop(.interval_ns(poll_for_stop_interval_ns));
        self.poll_for_stop = plusarg_bool("poll_for_stop", self.poll_for_stop)
        self.poll_for_stop_interval_ns = plusarg_int(
            "poll_for_stop_interval_ns",
            self.poll_for_stop_interval_ns,
        )
        # Start the background stop-poller as a real cocotb task. It
        # watches ``self._stop_requested`` and is cancelled once the
        # sequence finishes. Only meaningful under a live simulator.
        if self.poll_for_stop and cocotb.is_simulation:
            self._poll_task = cocotb.start_soon(self._poll_for_stop_loop())

        # SV:
        #   void'($value$plusargs("UVM_TEST_SEQ=%0s", test_seq_s));
        #   if (run_test_seq) run_seq(test_seq_s, phase);
        self.test_seq_s = plusarg_str("UVM_TEST_SEQ", self.test_seq_s)
        if self.run_test_seq and self.test_seq_s:
            if cocotb.is_simulation:
                # SV: uvm_top.set_timeout(test_timeout_ns).
                # cocotb enforces this by racing the sequence against a
                # Timer; SimTimeoutError is raised if the sequence runs
                # past the budget.
                try:
                    await with_timeout(
                        self.run_seq(self.test_seq_s),
                        self.test_timeout_ns,
                        "ns",
                    )
                except SimTimeoutError:
                    self._log.critical(
                        f"TEST TIMEOUT after {self.test_timeout_ns} ns "
                        f"while running sequence {self.test_seq_s!r}"
                    )
                    raise
                finally:
                    self._stop_poller()
            else:
                # No simulator: run the sequence directly. The timeout
                # and drain-time concepts have no meaning without sim
                # time, so we skip them.
                await self.run_seq(self.test_seq_s)

        # SV: phase.phase_done.set_drain_time(this, drain_time_ns * 1ns).
        # Let the design settle before ending the run. Real Timer under
        # a simulator; a no-op otherwise.
        if cocotb.is_simulation and self.drain_time_ns > 0:
            await Timer(self.drain_time_ns, "ns")

        # End-of-test summary, equivalent to ``report_phase`` /
        # ``report_summarize`` on the SV report server.
        if self.report_catcher is not None:
            self._log.info(self.report_catcher.summarize())

    # ------------------------------------------------------------------
    # poll_for_stop support — analogue of dv_utils_pkg::poll_for_stop.
    # ------------------------------------------------------------------
    def request_stop(self) -> None:
        """Ask the background poller to stop the test early. Mirrors the
        effect of the sentinel that ``dv_utils_pkg::poll_for_stop``
        watches in the SV flow.
        """
        self._stop_requested = True

    async def _poll_for_stop_loop(self) -> None:
        """Poll ``self._stop_requested`` every ``poll_for_stop_interval_ns``
        and log when a stop is observed. Runs as a background cocotb
        task; cancelled when the sequence finishes.
        """
        while True:
            await Timer(self.poll_for_stop_interval_ns, "ns")
            if self._stop_requested:
                self._log.info("poll_for_stop: stop requested, ending test")
                return

    def _stop_poller(self) -> None:
        """Cancel the background poll task if it is still running."""
        if self._poll_task is not None:
            try:
                self._poll_task.kill()
            except Exception:
                pass
            self._poll_task = None

    # ------------------------------------------------------------------
    # add_message_demotes — virtual hook with the same name and
    # signature as in SV.
    # ------------------------------------------------------------------
    def add_message_demotes(self, catcher: DVReportCatcher) -> None:
        """Override to register demote rules on ``catcher``. Default is a
        no-op, exactly like the SV base.
        """
        return

    # ------------------------------------------------------------------
    # run_seq — direct port. Skips the phase objection bookkeeping
    # because pyuvm doesn't have it.
    # ------------------------------------------------------------------
    async def run_seq(self, test_seq_s: str) -> None:
        test_seq = self.create_seq_by_name(test_seq_s)
        self.configure_sequence(test_seq)
        # SV: `DV_CHECK_RANDOMIZE_FATAL(test_seq)
        rand_ok = True
        rand_hook = getattr(test_seq, "randomize", None)
        if callable(rand_hook):
            try:
                rand_ok = bool(rand_hook())
            except Exception:
                rand_ok = False
        if not rand_ok:
            self._log.critical(f"Failed to randomize sequence {test_seq_s!r}")

        self._log.info(f"Starting test sequence {test_seq_s}")
        assert self.env is not None and self.env.virtual_sequencer is not None
        await test_seq.start(self.env.virtual_sequencer)
        self._log.info(f"Finished test sequence {test_seq_s}")

    # ------------------------------------------------------------------
    # configure_sequence — direct port of the virtual function.
    # ------------------------------------------------------------------
    def configure_sequence(self, seq: DVBaseSequence) -> None:
        """Hook the sequence will use to find the sequencer it should
        run on. The SV base sets ``seq.set_sequencer(env.virtual_sequencer)``;
        in pyuvm ``start(seqr)`` does the binding, so this default is a
        no-op. Override to wire up extra sequencer handles for
        sequences that need them.
        """
        return

    # ------------------------------------------------------------------
    # create_seq_by_name — analogue of UVM's ``create_seq_by_name``.
    # SystemVerilog uses the factory; we use Python's import system.
    # The lookup walks every loaded subclass of DVBaseSequence so the
    # user can register IP-specific sequences just by importing them.
    # ------------------------------------------------------------------
    def create_seq_by_name(self, name: str) -> DVBaseSequence:
        seq_cls = _find_seq_class(name)
        if seq_cls is None:
            raise LookupError(
                f"Could not find a DVBaseSequence subclass named {name!r}. "
                "Make sure the module defining it has been imported."
            )
        return seq_cls(name)

    # pyuvm's uvm_component already assigns ``self.logger`` in its
    # __init__, so we simply rely on that.


def _find_seq_class(name: str) -> Optional[Type[DVBaseSequence]]:
    """Walk every subclass of DVBaseSequence (recursively) and return
    the one whose ``__name__`` matches ``name``. Mirrors the behaviour
    of ``uvm_factory::create_object_by_name``.
    """
    stack = [DVBaseSequence]
    while stack:
        cls = stack.pop()
        if cls.__name__ == name:
            return cls
        stack.extend(cls.__subclasses__())
    return None
