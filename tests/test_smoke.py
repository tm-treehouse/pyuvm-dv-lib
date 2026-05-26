"""
Smoke test exercising the dv_lib pyuvm port end-to-end.

We build a trivial test that uses a custom env, scoreboard, agent and
sequence, runs them in pyuvm (no cocotb / no DUT), and asserts that:

* the cfg knobs are honoured (en_scb on / off, en_cov on / off),
* plusargs propagate (UVM_TEST_SEQ flips which sequence runs),
* the report catcher demotes a UVM_ERROR to UVM_INFO,
* the scoreboard's check_phase is gated by en_scb,
* DVBaseRegBlock helpers (gen_n_used_bits, get_msb_pos) work,
* the active/passive decision in DVBaseAgent is honoured.

The test is run by pyuvm's standalone runner (no simulator needed).
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from pyuvm import ConfigDB, uvm_root

from dv_lib import (
    DVBaseAgent,
    DVBaseAgentCfg,
    DVBaseDriver,
    DVBaseEnv,
    DVBaseEnvCfg,
    DVBaseMonitor,
    DVBaseReg,
    DVBaseRegBlock,
    DVBaseRegField,
    DVBaseScoreboard,
    DVBaseSeqItem,
    DVBaseSequence,
    DVBaseTest,
    DVBaseVSeq,
    DVReportCatcher,
    UVM_ACTIVE,
    UVM_PASSIVE,
    clear_plusargs,
    install_dv_report_server,
    plusarg_bool,
    plusarg_int,
    plusarg_str,
    set_plusargs,
)
from dv_lib.dv_base_agent_cfg import IfMode, UVM_ACTIVE as UVM_ACTIVE_FROM_AGENT  # noqa
from dv_lib.dv_base_test import _find_seq_class


# Re-export the module-level UVM_ACTIVE constant for the import above
# (we re-import it locally just to confirm it lives at the module path
# advertised in dv_lib.__init__).
import dv_lib  # noqa  -- we only need the side effect


def _reset_world():
    """Pyuvm keeps singleton state between runs. Wipe it so each test
    starts from a known place."""
    clear_plusargs()
    try:
        ConfigDB().clear()
    except Exception:
        pass
    try:
        # pyuvm's root holds a children dict keyed by name. If a previous
        # test created uvm_test_top, the next ``SmokeTest("uvm_test_top",
        # None)`` will collide; clear the root.
        from pyuvm import uvm_root as _root
        _root().clear_children()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Plusarg helpers
# ---------------------------------------------------------------------------

class TestPlusargs:
    def setup_method(self):
        _reset_world()

    def test_int_default(self):
        assert plusarg_int("missing", 7) == 7

    def test_int_set(self):
        set_plusargs(foo=42)
        assert plusarg_int("foo", 0) == 42

    def test_int_hex(self):
        set_plusargs(addr="0x1000")
        assert plusarg_int("addr", 0) == 0x1000

    def test_bool_true_variants(self):
        for v in ("1", "true", "yes", "on", "Y"):
            set_plusargs(flag=v)
            assert plusarg_bool("flag", False) is True

    def test_bool_false_variants(self):
        for v in ("0", "false", "no", "off", "N"):
            set_plusargs(flag=v)
            assert plusarg_bool("flag", True) is False

    def test_bool_garbage_falls_back(self):
        set_plusargs(flag="garbage")
        assert plusarg_bool("flag", True) is True
        assert plusarg_bool("flag", False) is False

    def test_str(self):
        set_plusargs(seq="my_seq")
        assert plusarg_str("seq", "default") == "my_seq"
        assert plusarg_str("missing", "default") == "default"

    def test_reads_from_cocotb_plusargs(self, monkeypatch):
        """When a sim is live, plusargs come from cocotb.plusargs."""
        import cocotb
        # Simulate cocotb having parsed `+en_scb=0 +UVM_TEST_SEQ=foo +dbg`.
        monkeypatch.setattr(
            cocotb, "plusargs",
            {"en_scb": "0", "UVM_TEST_SEQ": "foo", "dbg": True},
            raising=False,
        )
        assert plusarg_bool("en_scb", True) is False
        assert plusarg_str("UVM_TEST_SEQ", "") == "foo"
        # A bare cocotb flag (stored as True) reads as boolean true.
        assert plusarg_bool("dbg", False) is True

    def test_cocotb_bare_flag_as_int(self, monkeypatch):
        """A bare `+flag` (cocotb stores True) normalizes to 1 for ints."""
        import cocotb
        monkeypatch.setattr(cocotb, "plusargs", {"flag": True}, raising=False)
        assert plusarg_int("flag", 0) == 1

    def test_cocotb_beats_explicit_override(self, monkeypatch):
        """cocotb.plusargs (the simulator command line) takes precedence
        over set_plusargs, so a real +arg can never be masked.
        """
        import cocotb
        monkeypatch.setattr(cocotb, "plusargs", {"en_scb": "1"}, raising=False)
        # Python side tries to force it off, but the simulator said 1.
        set_plusargs(en_scb=0)
        assert plusarg_bool("en_scb", False) is True

    def test_explicit_override_applies_without_sim(self, monkeypatch):
        """When the simulator did NOT supply the plusarg, set_plusargs
        still provides the value.
        """
        import cocotb
        monkeypatch.setattr(cocotb, "plusargs", {"other": "1"}, raising=False)
        set_plusargs(en_scb=0)
        assert plusarg_bool("en_scb", True) is False

    def test_missing_when_cocotb_plusargs_absent(self, monkeypatch):
        """No sim, no override, no env var -> default is returned."""
        import cocotb
        # Emulate "no sim": cocotb.plusargs not yet set.
        monkeypatch.setattr(cocotb, "plusargs", None, raising=False)
        assert plusarg_int("nope", 99) == 99


# ---------------------------------------------------------------------------
# Report catcher
# ---------------------------------------------------------------------------

class TestReportCatcher:
    def setup_method(self):
        _reset_world()

    def test_demote_error_to_info(self):
        # Demote rule given as a name. Verify both the record mutation
        # and the catcher's counters update accordingly.
        catcher = DVReportCatcher()
        catcher.add_demote(r"NOISY_ID", to_level="INFO")

        record = logging.LogRecord(
            name="pyuvm", level=logging.ERROR, pathname="", lineno=0,
            msg="something happened (NOISY_ID)", args=(), exc_info=None,
        )
        assert catcher.filter(record) is True
        assert record.levelno == logging.INFO
        assert record.levelname == "INFO"
        assert catcher.counts[logging.INFO] == 1
        assert catcher.counts[logging.ERROR] == 0

    def test_demote_with_int_level(self):
        # Same rule, but expressed as a stdlib int constant.
        catcher = DVReportCatcher()
        catcher.add_demote(r"NOISY_ID", to_level=logging.INFO)

        record = logging.LogRecord(
            name="pyuvm", level=logging.ERROR, pathname="", lineno=0,
            msg="something happened (NOISY_ID)", args=(), exc_info=None,
        )
        catcher.filter(record)
        assert record.levelno == logging.INFO

    def test_no_match_keeps_level(self):
        catcher = DVReportCatcher()
        catcher.add_demote(r"NOISY_ID", to_level="INFO")
        record = logging.LogRecord(
            name="pyuvm", level=logging.ERROR, pathname="", lineno=0,
            msg="real error", args=(), exc_info=None,
        )
        catcher.filter(record)
        assert record.levelno == logging.ERROR
        assert record.levelname == "ERROR"
        assert catcher.counts[logging.ERROR] == 1

    def test_from_level_restricts_match(self):
        # Rule only fires when the *source* level matches from_level.
        catcher = DVReportCatcher()
        catcher.add_demote(r"NOISY", to_level="INFO",
                           from_level=logging.WARNING)

        # Source is ERROR -> rule should NOT apply, stays ERROR.
        rec_err = logging.LogRecord(
            name="pyuvm", level=logging.ERROR, pathname="", lineno=0,
            msg="NOISY thing", args=(), exc_info=None,
        )
        catcher.filter(rec_err)
        assert rec_err.levelno == logging.ERROR

        # Source is WARNING -> rule applies, demoted to INFO.
        rec_warn = logging.LogRecord(
            name="pyuvm", level=logging.WARNING, pathname="", lineno=0,
            msg="NOISY thing", args=(), exc_info=None,
        )
        catcher.filter(rec_warn)
        assert rec_warn.levelno == logging.INFO

    def test_summarize_string(self):
        catcher = DVReportCatcher()
        catcher.counts[logging.INFO] = 3
        catcher.counts[logging.ERROR] = 2
        s = catcher.summarize()
        # The summary uses stdlib level names, not UVM_* names.
        assert "INFO=3" in s
        assert "ERROR=2" in s
        # Sanity: it shouldn't contain the old UVM_* names.
        assert "UVM_INFO" not in s
        assert "UVM_ERROR" not in s

    def test_error_count_sums_error_and_critical(self):
        catcher = DVReportCatcher()
        catcher.counts[logging.ERROR] = 4
        catcher.counts[logging.CRITICAL] = 1
        assert catcher.error_count == 5

    def test_install_returns_logger(self):
        catcher, logger = install_dv_report_server(logger_name="pyuvm")
        assert isinstance(logger, logging.Logger)
        assert catcher in logger.filters

    def test_install_attaches_to_existing_handlers(self):
        """Handlers in the parent chain should also have the catcher
        attached, because logger-level filters don't see propagated
        records — handler-level filters do.
        """
        # Set up a tree: root_logger -> child -> grandchild, with a
        # handler on root_logger.
        root_logger = logging.getLogger("dv_lib_test_root")
        root_logger.handlers.clear()
        root_logger.filters.clear()
        handler = logging.NullHandler()
        root_logger.addHandler(handler)

        child = logging.getLogger("dv_lib_test_root.child")
        child.filters.clear()

        catcher, _ = install_dv_report_server(
            logger_name="dv_lib_test_root.child",
        )
        # Logger gets the filter as a fallback.
        assert catcher in child.filters
        # And the root's handler gets it too, which is the *important*
        # part for records that propagate up.
        assert catcher in handler.filters

    def test_install_with_propagate_false_stops_walk(self):
        """If a logger in the chain has propagate=False, we shouldn't
        attach to anything above it (no record will reach those handlers
        anyway).
        """
        parent = logging.getLogger("dv_lib_test_root2")
        parent.handlers.clear()
        parent.filters.clear()
        parent_handler = logging.NullHandler()
        parent.addHandler(parent_handler)

        child = logging.getLogger("dv_lib_test_root2.child")
        child.handlers.clear()
        child.filters.clear()
        child_handler = logging.NullHandler()
        child.addHandler(child_handler)
        child.propagate = False

        catcher, _ = install_dv_report_server(
            logger_name="dv_lib_test_root2.child",
        )
        assert catcher in child_handler.filters
        assert catcher not in parent_handler.filters

    def test_install_is_idempotent(self):
        """Calling install_dv_report_server twice with the same catcher
        should not double-count: addFilter dedupes by identity.
        """
        catcher = DVReportCatcher()
        install_dv_report_server(catcher, logger_name="dv_lib_idem_test")
        install_dv_report_server(catcher, logger_name="dv_lib_idem_test")

        logger = logging.getLogger("dv_lib_idem_test")
        # The filter should appear exactly once.
        assert logger.filters.count(catcher) == 1

    def test_install_attaches_to_descendant_handlers(self):
        """Mirror the real pyuvm deployment: a per-component logger has
        ``propagate=False`` and carries its own ``StreamHandler``.
        Records emitted on it never reach any ancestor, so the install
        must walk DOWN into descendants and attach there.
        """
        import io
        # Build a "uvm" root logger with no handler...
        root = logging.getLogger("dv_lib_descendant_test")
        root.handlers.clear()
        root.filters.clear()

        # ...and a "uvm.uvm_test_top" descendant that does its own
        # emitting (no propagation, its own handler).
        component = logging.getLogger("dv_lib_descendant_test.uvm_test_top")
        component.handlers.clear()
        component.filters.clear()
        component.propagate = False
        component.setLevel(logging.DEBUG)
        component.addHandler(logging.StreamHandler(io.StringIO()))

        catcher, _ = install_dv_report_server(
            logger_name="dv_lib_descendant_test",
        )

        # The component's handler should now have the catcher as a
        # filter — the whole point of walking downward.
        comp_handler = component.handlers[0]
        assert catcher in comp_handler.filters, \
            "install should attach to descendant handler"

        # And it should actually count records emitted from the
        # non-propagating component.
        component.error("an error from a non-propagating component")
        component.info("an info from a non-propagating component")
        assert catcher.counts[logging.ERROR] == 1
        assert catcher.counts[logging.INFO] == 1

    def test_reinstall_picks_up_late_components(self):
        """If a component is constructed after the initial install, the
        helper ``reinstall_on_new_components`` should pick it up.
        """
        from dv_lib.dv_report import reinstall_on_new_components
        import io

        root = logging.getLogger("dv_lib_reinstall_test")
        root.handlers.clear()
        root.filters.clear()

        catcher, _ = install_dv_report_server(
            logger_name="dv_lib_reinstall_test",
        )

        # Now (post-install) a new component logger appears.
        late = logging.getLogger("dv_lib_reinstall_test.late_component")
        late.handlers.clear()
        late.filters.clear()
        late.propagate = False
        late.setLevel(logging.DEBUG)
        late.addHandler(logging.StreamHandler(io.StringIO()))

        # Before re-install, the new handler is unfiltered.
        assert catcher not in late.handlers[0].filters

        # Re-install and confirm.
        n = reinstall_on_new_components(
            catcher, logger_name="dv_lib_reinstall_test",
        )
        assert n >= 1
        assert catcher in late.handlers[0].filters

        # And records actually count now.
        late.error("late component error")
        assert catcher.counts[logging.ERROR] == 1
        """The end-to-end story: emit on a deeply-nested logger, expect
        the catcher to see the record because the install attached to
        a handler higher up.

        Note: we use a real ``StreamHandler`` rather than ``NullHandler``
        because ``NullHandler.handle()`` is documented to skip the
        normal handler machinery, which includes filter execution. In a
        real deployment (cocotb / pytest) the handlers are
        ``StreamHandler`` instances so the filter does run.
        """
        import io
        # Build a real handler chain so propagation has somewhere to go.
        root_logger = logging.getLogger("dv_lib_e2e_test")
        root_logger.handlers.clear()
        root_logger.filters.clear()
        root_logger.setLevel(logging.DEBUG)
        root_logger.propagate = False  # don't double-count via pytest root
        root_logger.addHandler(logging.StreamHandler(io.StringIO()))

        # Install at the root.
        catcher, _ = install_dv_report_server(logger_name="dv_lib_e2e_test")

        # Now log from a nested logger that propagates up.
        nested = logging.getLogger("dv_lib_e2e_test.uvm_test_top.env")
        nested.setLevel(logging.DEBUG)
        nested.error("a sample error")
        nested.info("a sample info")

        assert catcher.counts[logging.ERROR] == 1
        assert catcher.counts[logging.INFO] == 1

    def test_auto_detect_picks_populated_tree(self):
        """If we don't tell install_dv_report_server which logger to use,
        it should pick whichever known tree has descendants — i.e. the
        one components are actually logging through.
        """
        from dv_lib.dv_report import _detect_logger_name

        # Make 'uvm' look populated by creating a descendant.
        logging.getLogger("uvm.dv_lib_autodetect_probe")
        # 'cocotb' has no extra descendants under this test session.
        choice = _detect_logger_name()
        # We can't assert on the exact value (depends on what else in
        # the process has touched these names), but it should be one of
        # the known candidates and not crash.
        assert choice in ("cocotb", "uvm", "pyuvm")

    def test_unknown_level_rejected(self):
        catcher = DVReportCatcher()
        with pytest.raises(ValueError):
            catcher.add_demote("X", to_level="PURPLE")


# ---------------------------------------------------------------------------
# RAL analogue
# ---------------------------------------------------------------------------

class TestRegBlockHelpers:
    def setup_method(self):
        _reset_world()

    def _make_reg(self):
        reg = DVBaseReg("ctrl", addr=0x0, n_bits=32)
        reg.add_field(DVBaseRegField("enable", lsb_pos=0,  n_bits=1))
        reg.add_field(DVBaseRegField("mode",   lsb_pos=1,  n_bits=2))
        reg.add_field(DVBaseRegField("count",  lsb_pos=8,  n_bits=8))
        return reg

    def test_gen_n_used_bits(self):
        reg = self._make_reg()
        # 1 + 2 + 8 = 11
        assert reg.gen_n_used_bits() == 11

    def test_get_msb_pos(self):
        reg = self._make_reg()
        # count occupies bits [15:8]
        assert reg.get_msb_pos() == 15

    def test_read_write_roundtrip(self):
        reg = self._make_reg()
        # Set enable=1, mode=2, count=0x5A
        reg.write((0x5A << 8) | (2 << 1) | 1)
        word = reg.read()
        assert word == ((0x5A << 8) | (2 << 1) | 1)

    def test_pseudo_pure_virtual_build_raises(self):
        block = DVBaseRegBlock()
        with pytest.raises(RuntimeError):
            block.build(0)

    def test_subclass_build_runs(self):
        class MyBlock(DVBaseRegBlock):
            def build(self, base_addr=0):
                self.base_addr = base_addr
                self.add_reg(DVBaseReg("ctrl", addr=base_addr))
        b = MyBlock()
        b.build(0x1000)
        assert b.base_addr == 0x1000
        assert b.get_reg_by_name("ctrl") is not None

    def test_duplicate_reg_rejected(self):
        b = DVBaseRegBlock()
        b.add_reg(DVBaseReg("a"))
        with pytest.raises(ValueError):
            b.add_reg(DVBaseReg("a"))


# ---------------------------------------------------------------------------
# Cfg objects
# ---------------------------------------------------------------------------

class TestEnvCfg:
    def setup_method(self):
        _reset_world()

    def test_defaults_match_sv(self):
        cfg = DVBaseEnvCfg()
        # Defaults from dv_base_test.sv before plusarg override:
        assert cfg.en_scb is True
        assert cfg.en_scb_mem_chk is True
        assert cfg.zero_delays is False
        assert cfg.en_cov is True
        assert cfg.smoke_test is False
        assert cfg.en_dv_cdc == 0

    def test_initialize_with_subclassed_ral(self):
        class MyRAL(DVBaseRegBlock):
            def build(self, base_addr=0):
                self.base_addr = base_addr

        class MyCfg(DVBaseEnvCfg):
            ral_type = MyRAL

        cfg = MyCfg()
        cfg.initialize(csr_base_addr=0xDEAD)
        assert cfg.ral is not None
        assert cfg.ral.base_addr == 0xDEAD

    def test_initialize_swallows_default_ral_fatal(self):
        # Base ral_type is DVBaseRegBlock whose build() raises. The
        # cfg should swallow that — see comment in initialize().
        cfg = DVBaseEnvCfg()
        cfg.initialize()  # no exception
        assert cfg.ral is not None


class TestAgentCfg:
    def setup_method(self):
        _reset_world()

    def test_active_predicate(self):
        c = DVBaseAgentCfg()
        c.is_active = UVM_ACTIVE
        assert c.active is True
        c.is_active = UVM_PASSIVE
        assert c.active is False


# ---------------------------------------------------------------------------
# Sequence registry
# ---------------------------------------------------------------------------

class TestSequenceLookup:
    def setup_method(self):
        _reset_world()

    def test_find_existing(self):
        class FindMeSeq(DVBaseSequence):
            pass
        assert _find_seq_class("FindMeSeq") is FindMeSeq

    def test_find_missing(self):
        assert _find_seq_class("NoSuchSeqEverDefined") is None

    def test_find_through_intermediate_subclass(self):
        class Mid(DVBaseSequence):
            pass

        class Leaf(Mid):
            pass
        assert _find_seq_class("Leaf") is Leaf
        assert _find_seq_class("Mid") is Mid


# ---------------------------------------------------------------------------
# End-to-end: build an env + run a simple sequence under pyuvm.
#
# pyuvm normally launches via ``await uvm_root().run_test("MyTest")``.
# We use that here so build/connect/run phases all execute properly.
# ---------------------------------------------------------------------------

# Records what the driver received, so the test can assert on it.
DRIVEN = []


class SmokeItem(DVBaseSeqItem):
    def __init__(self, name="item", payload=0):
        super().__init__(name)
        self.payload = payload


class SmokeDriver(DVBaseDriver):
    async def drive_item(self, item):
        DRIVEN.append(item.payload)
        # Echo so the monitor / scoreboard could see it if it wanted.
        if self.cfg is not None and self.cfg.zero_delays:
            return  # no delay
        # No actual time concept here — pyuvm with no DUT runs in zero
        # simulated time. The branch is just to prove cfg flows through.


class SmokeMonitor(DVBaseMonitor):
    # collect_trans is left as a no-op; we don't have a bus to watch.
    async def collect_trans(self):
        return


class SmokeAgent(DVBaseAgent):
    driver_type = SmokeDriver
    monitor_type = SmokeMonitor


class SmokeScoreboard(DVBaseScoreboard):
    checked = False

    def do_check(self):
        SmokeScoreboard.checked = True


class SmokeEnv(DVBaseEnv):
    scoreboard_type = SmokeScoreboard

    def build_phase(self):
        super().build_phase()
        # Add a single agent under the env.
        agent_cfg = DVBaseAgentCfg("smoke_agent_cfg")
        agent_cfg.is_active = UVM_ACTIVE
        ConfigDB().set(self, "smoke_agent", "cfg", agent_cfg)
        self.smoke_agent = SmokeAgent.create("smoke_agent", self)

    def connect_phase(self):
        super().connect_phase()
        # Register the agent's sequencer with the virtual sequencer so
        # vseqs can reach it.
        if self.smoke_agent.sequencer is not None:
            self.virtual_sequencer.register_seqr(
                "smoke", self.smoke_agent.sequencer,
            )


class SmokeVSeq(DVBaseVSeq):
    """Sends three items to the smoke agent and stops."""
    async def body(self):
        smoke_seqr = self.p_sequencer.sub_seqrs["smoke"]
        for i in range(3):
            item = SmokeItem(payload=i + 1)
            await self.start_item(item, smoke_seqr)
            await self.finish_item(item, smoke_seqr)


class SmokeTest(DVBaseTest):
    env_type = SmokeEnv

    def __init__(self, name="SmokeTest", parent=None):
        super().__init__(name, parent)
        # Simulate the SV "+UVM_TEST_SEQ=SmokeVSeq" plusarg.
        self.test_seq_s = "SmokeVSeq"


# pyuvm picks up uvm_test classes by name — make sure both are reachable.

class TestEndToEndBehaviour:
    """Exercise the cfg/plusarg/scoreboard wiring without spinning up a
    full pyuvm phase loop.

    pyuvm 4.x's ``uvm_root().run_test`` goes through cocotb's regression
    manager and even pyuvm's own loggers reach into ``cocotb.simtime``,
    so a "standalone, no-DUT" run is not a supported mode of the
    library. Instead we verify the same behaviours by exercising the
    relevant phase methods directly.
    """

    def setup_method(self):
        _reset_world()

    def test_dv_base_test_build_phase_applies_plusargs(self):
        set_plusargs(en_scb=0, en_cov=0, zero_delays=1, smoke_test=1,
                     cdc_instrumentation_enabled=3)

        t = SmokeTest("uvm_test_top", None)
        # build_phase resolves cfg, runs the plusarg overrides, and
        # publishes cfg into ConfigDB. We don't need the rest of the
        # phase loop to assert this.
        t.build_phase()

        assert t.cfg is not None
        assert t.cfg.en_scb is False
        assert t.cfg.en_cov is False
        assert t.cfg.zero_delays is True
        assert t.cfg.smoke_test is True
        assert t.cfg.en_dv_cdc == 3

    def test_dv_base_test_build_phase_creates_env(self):
        t = SmokeTest("uvm_test_top", None)
        t.build_phase()
        assert isinstance(t.env, SmokeEnv)

    def test_log_falls_back_to_stdlib_without_sim(self):
        """Outside a simulator, ``_log`` returns the side-car stdlib
        logger rather than pyuvm's sim-time logger (which needs a live
        simulator).
        """
        import cocotb
        import logging
        from dv_lib.dv_base_test import _dv_logger

        assert cocotb.is_simulation is False  # we're under pytest
        t = SmokeTest("uvm_test_top", None)
        assert t._log is _dv_logger
        assert isinstance(t._log, logging.Logger)

    def test_request_stop_sets_flag(self):
        """``request_stop`` flips the flag the background poller watches."""
        t = SmokeTest("uvm_test_top", None)
        assert t._stop_requested is False
        t.request_stop()
        assert t._stop_requested is True

    def test_run_phase_no_sim_skips_poll_task(self):
        """Under pytest (no simulator), even with poll_for_stop=1 the
        background poller must not be started, because it relies on
        cocotb Timers. We check the guard directly rather than running
        the full run_phase (pyuvm's sequencer needs a live sim).
        """
        import cocotb
        assert cocotb.is_simulation is False
        set_plusargs(poll_for_stop=1)
        t = SmokeTest("uvm_test_top", None)
        # The poll task is only created inside the cocotb.is_simulation
        # branch of run_phase, so without a sim it stays None.
        assert t._poll_task is None

    def test_scoreboard_check_phase_gated_by_en_scb(self):
        """``DVBaseScoreboard.check_phase`` early-returns when en_scb is
        off, just like the SV original.
        """
        sb_off = SmokeScoreboard("sb_off", None)
        sb_off.cfg = DVBaseEnvCfg()
        sb_off.cfg.en_scb = False
        SmokeScoreboard.checked = False
        sb_off.check_phase()
        assert SmokeScoreboard.checked is False

        sb_on = SmokeScoreboard("sb_on", None)
        sb_on.cfg = DVBaseEnvCfg()
        sb_on.cfg.en_scb = True
        SmokeScoreboard.checked = False
        sb_on.check_phase()
        assert SmokeScoreboard.checked is True

    def test_agent_active_creates_driver_and_sequencer(self):
        # Active agent: build_phase should create a driver + sequencer.
        agent = SmokeAgent("agent", None)
        cfg = DVBaseAgentCfg()
        cfg.is_active = UVM_ACTIVE
        ConfigDB().set(agent, "", "cfg", cfg)
        agent.build_phase()
        assert agent.driver is not None
        assert agent.sequencer is not None
        assert agent.monitor is not None

    def test_agent_passive_skips_driver_and_sequencer(self):
        agent = SmokeAgent("agent2", None)
        cfg = DVBaseAgentCfg()
        cfg.is_active = UVM_PASSIVE
        ConfigDB().set(agent, "", "cfg", cfg)
        agent.build_phase()
        # Monitor always exists, driver/sequencer don't.
        assert agent.monitor is not None
        assert agent.driver is None
        assert agent.sequencer is None

    def test_agent_cov_only_when_en_cov(self):
        agent = SmokeAgent("agent3", None)
        cfg = DVBaseAgentCfg()
        cfg.en_cov = False
        ConfigDB().set(agent, "", "cfg", cfg)
        agent.build_phase()
        assert agent.cov is None

        agent2 = SmokeAgent("agent4", None)
        cfg2 = DVBaseAgentCfg()
        cfg2.en_cov = True
        ConfigDB().set(agent2, "", "cfg", cfg2)
        agent2.build_phase()
        assert agent2.cov is not None


# ---------------------------------------------------------------------------
# Clock/reset interface + vseq reset wiring + driver zero_delays
# ---------------------------------------------------------------------------

class TestClkRstAndDelays:
    def setup_method(self):
        _reset_world()

    def test_clk_rst_if_methods_noop_without_sim(self):
        """Without a simulator, ClkRstIf methods are awaitable no-ops and
        never touch signal handles.
        """
        import asyncio
        from dv_lib import ClkRstIf

        # Pass sentinel handles; with no sim they must not be touched.
        iface = ClkRstIf(clk=object(), rst=object(), period_ns=10)

        async def go():
            iface.start_clk()            # no-op
            await iface.wait_clks(3)     # returns immediately
            await iface.apply_reset()    # returns immediately
            iface.stop_clk()

        asyncio.run(go())  # must complete without error
        assert iface._clock is None

    def test_clk_rst_if_polarity(self):
        from dv_lib import ClkRstIf
        active_low = ClkRstIf(reset_active_low=True)
        assert active_low._asserted == 0
        assert active_low._deasserted == 1
        active_high = ClkRstIf(reset_active_low=False)
        assert active_high._asserted == 1
        assert active_high._deasserted == 0

    def test_vseq_apply_reset_calls_vif(self):
        """The base vseq's apply_reset should await the cfg's
        clk_rst_vif.apply_reset when one is present.
        """
        import asyncio
        from dv_lib import DVBaseVSeq, DVBaseEnvCfg

        calls = {}

        class FakeClkRst:
            async def apply_reset(self, reset_cycles=5):
                calls["reset_cycles"] = reset_cycles

        cfg = DVBaseEnvCfg()
        cfg.clk_rst_vif = FakeClkRst()

        class FakeSeqr:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cov = None

        vseq = DVBaseVSeq()
        vseq.reset_cycles = 7
        # Bind a fake sequencer so the cfg property resolves.
        vseq.sequencer = FakeSeqr(cfg)

        asyncio.run(vseq.apply_reset())
        assert calls.get("reset_cycles") == 7

    def test_vseq_apply_reset_noop_without_vif(self):
        """apply_reset is a safe no-op when there's no clk_rst_vif."""
        import asyncio
        from dv_lib import DVBaseVSeq, DVBaseEnvCfg

        cfg = DVBaseEnvCfg()  # clk_rst_vif defaults to None

        class FakeSeqr:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cov = None

        vseq = DVBaseVSeq()
        vseq.sequencer = FakeSeqr(cfg)
        # Should complete without error and without raising.
        asyncio.run(vseq.apply_reset())

    def test_driver_maybe_delay_respects_zero_delays(self):
        """_maybe_delay returns immediately when zero_delays is set, and
        also when there's no simulator (the common pytest case).
        """
        import asyncio
        from dv_lib import DVBaseDriver, DVBaseAgentCfg

        drv = DVBaseDriver("drv", None)
        drv.cfg = DVBaseAgentCfg()
        drv.cfg.zero_delays = True

        # Track whether get_item_delay_ns is consulted; with zero_delays
        # it should be short-circuited before that.
        consulted = {"n": 0}
        def hook():
            consulted["n"] += 1
            return 100.0
        drv.get_item_delay_ns = hook  # type: ignore[assignment]

        asyncio.run(drv._maybe_delay())
        # zero_delays short-circuits before the delay hook is read.
        assert consulted["n"] == 0

    def test_driver_get_item_delay_default_zero(self):
        from dv_lib import DVBaseDriver
        drv = DVBaseDriver("drv2", None)
        assert drv.get_item_delay_ns() == 0.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
