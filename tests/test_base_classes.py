"""
Unit tests for base-class behaviours that the smoke / example suites
don't already cover. These focus on pure-Python paths (no simulator
required): seq-item copy/compare, RAL field/reg helpers, cfg defaults,
sequence/vseq handle resolution, report-level coercion edge cases, and
the no-sim branches of the clock/reset interface.
"""
from __future__ import annotations

import asyncio
import logging

import pytest
from pyuvm import ConfigDB

from dv_lib import (
    ClkRstIf,
    DVBaseAgentCfg,
    DVBaseDriver,
    DVBaseEnvCfg,
    DVBaseReg,
    DVBaseRegBlock,
    DVBaseRegField,
    DVBaseSeqItem,
    DVBaseSequence,
    DVBaseVSeq,
    DVReportCatcher,
)


def _reset_world():
    try:
        ConfigDB().clear()
    except Exception:
        pass
    try:
        from pyuvm import uvm_root as _root
        _root().clear_children()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# DVBaseSeqItem: do_copy / do_compare / _state_dict
# ---------------------------------------------------------------------------

class _Item(DVBaseSeqItem):
    def __init__(self, name="item", a=0, b=0):
        super().__init__(name)
        self.a = a
        self.b = b


class TestSeqItem:
    def setup_method(self):
        _reset_world()

    def test_state_dict_excludes_private_and_name(self):
        it = _Item(a=1, b=2)
        sd = it._state_dict()
        assert sd == {"a": 1, "b": 2}
        assert "name" not in sd

    def test_do_copy(self):
        src = _Item(a=5, b=6)
        dst = _Item()
        dst.do_copy(src)
        assert (dst.a, dst.b) == (5, 6)

    def test_do_compare_equal(self):
        assert _Item(a=1, b=2).do_compare(_Item(a=1, b=2)) is True

    def test_do_compare_unequal_values(self):
        assert _Item(a=1, b=2).do_compare(_Item(a=1, b=9)) is False

    def test_do_compare_unequal_types(self):
        class _Other(DVBaseSeqItem):
            def __init__(self):
                super().__init__("other")
                self.a = 1
                self.b = 2
        assert _Item(a=1, b=2).do_compare(_Other()) is False

    def test_str_roundtrips_fields(self):
        s = str(_Item(a=1, b=2))
        assert "_Item" in s and "a=1" in s and "b=2" in s


# ---------------------------------------------------------------------------
# DVBaseRegField / DVBaseReg / DVBaseRegBlock extra paths
# ---------------------------------------------------------------------------

class TestRegFieldExtras:
    def test_field_rejects_nonpositive_width(self):
        with pytest.raises(ValueError):
            DVBaseRegField("bad", lsb_pos=0, n_bits=0)
        with pytest.raises(ValueError):
            DVBaseRegField("bad", lsb_pos=0, n_bits=-3)

    def test_field_msb_and_mask(self):
        f = DVBaseRegField("f", lsb_pos=4, n_bits=4)
        assert f.msb_pos == 7
        assert f.mask == 0xF0

    def test_field_reset_value(self):
        f = DVBaseRegField("f", lsb_pos=0, n_bits=8, reset=0xAB)
        assert f.value == 0xAB

    def test_reg_empty_get_msb_pos(self):
        # No fields -> get_msb_pos returns -1 per the implementation.
        reg = DVBaseReg("empty")
        assert reg.get_msb_pos() == -1
        assert reg.gen_n_used_bits() == 0

    def test_reg_fields_returns_copy(self):
        reg = DVBaseReg("r")
        reg.add_field(DVBaseRegField("a", 0, 1))
        fields = reg.fields
        fields.clear()  # mutating the returned list must not affect the reg
        assert len(reg.fields) == 1

    def test_block_get_reg_by_name_missing(self):
        b = DVBaseRegBlock()
        assert b.get_reg_by_name("nope") is None

    def test_block_regs_property(self):
        b = DVBaseRegBlock()
        b.add_reg(DVBaseReg("x"))
        b.add_reg(DVBaseReg("y"))
        names = [r.name for r in b.regs]
        assert names == ["x", "y"]

    def test_block_reset_restores_field_reset_values(self):
        b = DVBaseRegBlock()
        reg = DVBaseReg("ctrl")
        reg.add_field(DVBaseRegField("en", 0, 1, reset=1))
        reg.add_field(DVBaseRegField("mode", 1, 2, reset=2))
        b.add_reg(reg)
        # Scribble over the fields, then reset.
        reg.write(0)
        assert reg.read() == 0
        b.reset()
        # en back to 1, mode back to 2 -> (2<<1)|1 == 5
        assert reg.read() == ((2 << 1) | 1)


# ---------------------------------------------------------------------------
# DVBaseAgentCfg / DVBaseEnvCfg defaults & repr
# ---------------------------------------------------------------------------

class TestCfgDefaults:
    def test_agent_cfg_repr_contains_knobs(self):
        r = repr(DVBaseAgentCfg())
        assert "if_mode" in r and "zero_delays" in r

    def test_env_cfg_repr_contains_knobs(self):
        r = repr(DVBaseEnvCfg())
        assert "en_scb" in r and "agents=" in r

    def test_env_cfg_add_get_agent_cfg(self):
        cfg = DVBaseEnvCfg()
        ac = DVBaseAgentCfg("inner")
        cfg.add_agent_cfg("k", ac)
        assert cfg.get_agent_cfg("k") is ac
        assert cfg.get_agent_cfg("missing") is None

    def test_env_cfg_randomize_default_true(self):
        assert DVBaseEnvCfg().randomize() is True

    def test_env_cfg_clk_rst_vif_defaults_none(self):
        assert DVBaseEnvCfg().clk_rst_vif is None


# ---------------------------------------------------------------------------
# DVBaseSequence / DVBaseVSeq handle resolution without a sequencer
# ---------------------------------------------------------------------------

class TestSequenceHandles:
    def test_sequence_cfg_none_without_sequencer(self):
        seq = DVBaseSequence("s")
        assert seq.cfg is None
        assert seq.p_sequencer is None

    def test_sequence_cfg_from_sequencer(self):
        seq = DVBaseSequence("s")

        class FakeSeqr:
            cfg = "the_cfg"
        seq.sequencer = FakeSeqr()
        assert seq.cfg == "the_cfg"

    def test_vseq_handles_none_without_sequencer(self):
        v = DVBaseVSeq("v")
        assert v.cfg is None
        assert v.cov is None
        assert v.ral is None

    def test_vseq_ral_from_cfg(self):
        v = DVBaseVSeq("v")
        cfg = DVBaseEnvCfg()
        cfg.ral = "the_ral"

        class FakeSeqr:
            def __init__(self, cfg):
                self.cfg = cfg
                self.cov = "the_cov"
        v.sequencer = FakeSeqr(cfg)
        assert v.ral == "the_ral"
        assert v.cov == "the_cov"


# ---------------------------------------------------------------------------
# DVReportCatcher level coercion edge cases
# ---------------------------------------------------------------------------

class TestReportLevelCoercion:
    def test_lowercase_name_accepted(self):
        c = DVReportCatcher()
        c.add_demote("X", to_level="warning")  # lowercase
        # The rule's to_level should resolve to logging.WARNING.
        assert c.rules[0].to_level == logging.WARNING

    def test_custom_int_level_allowed(self):
        c = DVReportCatcher()
        c.add_demote("X", to_level=25)  # between INFO and WARNING
        assert c.rules[0].to_level == 25

    def test_from_level_as_name(self):
        c = DVReportCatcher()
        c.add_demote("X", to_level="INFO", from_level="ERROR")
        assert c.rules[0].from_level == logging.ERROR

    def test_summary_counts_custom_level_is_separate(self):
        # A record at a non-standard level still increments a bucket,
        # even though summarize() only iterates the canonical LEVELS.
        c = DVReportCatcher()
        rec = logging.LogRecord("pyuvm", 25, "", 0, "msg", (), None)
        c.filter(rec)
        assert c.counts.get(25) == 1


# ---------------------------------------------------------------------------
# ClkRstIf no-sim behaviour and repr
# ---------------------------------------------------------------------------

class TestClkRstIf:
    def test_repr_reports_handles(self):
        iface = ClkRstIf(clk=object(), rst=None, period_ns=5)
        r = repr(iface)
        assert "period_ns=5" in r
        assert "clk=set" in r
        assert "rst=None" in r

    def test_stop_clk_safe_when_not_started(self):
        iface = ClkRstIf()
        iface.stop_clk()  # must not raise
        assert iface._clock is None

    def test_wait_and_reset_are_noops_without_sim(self):
        iface = ClkRstIf(clk=object(), rst=object())

        async def go():
            await iface.wait_clks(5)
            await iface.wait_rising_edge()
            await iface.apply_reset(reset_cycles=10)
        asyncio.run(go())  # all return immediately


# ---------------------------------------------------------------------------
# DVBaseDriver delay hook (no-sim path)
# ---------------------------------------------------------------------------

class TestDriverDelay:
    def setup_method(self):
        _reset_world()

    def test_maybe_delay_noop_without_sim_even_if_delays_enabled(self):
        drv = DVBaseDriver("d", None)
        drv.cfg = DVBaseAgentCfg()
        drv.cfg.zero_delays = False  # delays "enabled"...
        # ...but no simulator, so _maybe_delay must still return at once
        # and never consult the delay hook.
        consulted = {"n": 0}

        def hook():
            consulted["n"] += 1
            return 50.0
        drv.get_item_delay_ns = hook  # type: ignore[assignment]
        asyncio.run(drv._maybe_delay())
        assert consulted["n"] == 0

    def test_maybe_delay_noop_when_cfg_missing(self):
        drv = DVBaseDriver("d2", None)
        drv.cfg = None
        asyncio.run(drv._maybe_delay())  # must not raise


# ---------------------------------------------------------------------------
# dv_utils internal parser + dv_report auto-detect fallback
# ---------------------------------------------------------------------------

class TestPlusargStringParser:
    def test_parses_key_value_and_flags(self):
        from dv_lib.dv_utils import _parse_plusarg_string
        out = _parse_plusarg_string("+en_scb=1 +UVM_TEST_SEQ=foo +verbose")
        assert out == {"en_scb": "1", "UVM_TEST_SEQ": "foo", "verbose": "1"}

    def test_ignores_non_plus_tokens(self):
        from dv_lib.dv_utils import _parse_plusarg_string
        out = _parse_plusarg_string("garbage +a=2 noise")
        assert out == {"a": "2"}

    def test_value_with_equals_keeps_remainder(self):
        from dv_lib.dv_utils import _parse_plusarg_string
        # Only the first '=' splits key/value.
        out = _parse_plusarg_string("+path=a=b=c")
        assert out == {"path": "a=b=c"}


class TestReportAutoDetect:
    def test_detect_returns_known_candidate(self):
        from dv_lib.dv_report import _detect_logger_name, _AUTO_LOGGER_CANDIDATES
        assert _detect_logger_name() in _AUTO_LOGGER_CANDIDATES


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
