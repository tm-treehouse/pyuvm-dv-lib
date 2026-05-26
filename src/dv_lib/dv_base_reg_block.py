# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_reg_block, dv_base_reg, dv_base_reg_field: Minimal RAL analogue.

The original SV classes extend the UVM RAL primitives
(``uvm_reg_block`` / ``uvm_reg`` / ``uvm_reg_field``) and add the
following IP-specific helpers, documented in the OpenTitan
``dv_lib`` README:

* ``dv_base_reg_field`` — currently no extra features; future plan is
  to support exclusion tags for the auto-generated CSR test suite.
* ``dv_base_reg``:
    - ``gen_n_used_bits()`` — sum of all field widths in the register.
    - ``get_msb_pos()`` — MSB position of the highest field.
* ``dv_base_reg_block``:
    - ``build(base_addr)`` — pseudo-pure-virtual; the SV implementation
      calls ``uvm_fatal`` if the user invokes it without overriding.
      It's used so that a (templated) test class can hold a
      ``dv_base_reg_block`` handle that's actually pointing at an
      IP-specific RAL model.

pyuvm has no RAL, so this file is a deliberately small Python-native
register model: enough to mirror the surface area and the helpers.
A full RAL replacement is well beyond the scope of a port of dv_lib —
testbenches that actually need register access usually layer cocotb's
register-access calls or a tool-generated model on top.
"""
from __future__ import annotations

from typing import Dict, List, Optional


class DVBaseRegField:
    """Single field inside a register.

    Mirrors ``dv_base_reg_field``. Currently carries no extra logic
    over a plain dataclass-like container — exactly matching the SV
    parent, which the OpenTitan README explicitly notes "does not
    provide any additional features" today.
    """

    def __init__(
        self,
        name: str,
        lsb_pos: int,
        n_bits: int,
        access: str = "RW",
        reset: int = 0,
    ) -> None:
        if n_bits <= 0:
            raise ValueError("Field width must be positive")
        self.name = name
        self.lsb_pos = lsb_pos
        self.n_bits = n_bits
        self.access = access
        self.reset = reset
        self.value: int = reset

    @property
    def msb_pos(self) -> int:
        return self.lsb_pos + self.n_bits - 1

    @property
    def mask(self) -> int:
        return ((1 << self.n_bits) - 1) << self.lsb_pos


class DVBaseReg:
    """Single register, holding zero or more :class:`DVBaseRegField`.

    Mirrors ``dv_base_reg``. The two user-visible helpers documented
    in the README, :meth:`gen_n_used_bits` and :meth:`get_msb_pos`,
    are implemented exactly as described:

    * ``gen_n_used_bits()`` returns the sum of every field's width;
    * ``get_msb_pos()`` returns the MSB position of the highest field.
    """

    def __init__(self, name: str, addr: int = 0, n_bits: int = 32) -> None:
        self.name = name
        self.addr = addr
        self.n_bits = n_bits
        self._fields: List[DVBaseRegField] = []

    # -------------- field plumbing ---------------------------------

    def add_field(self, field: DVBaseRegField) -> None:
        self._fields.append(field)

    @property
    def fields(self) -> List[DVBaseRegField]:
        return list(self._fields)

    # -------------- documented helpers -----------------------------

    def gen_n_used_bits(self) -> int:
        """Sum of all field widths (i.e. how many bits the register
        actually uses, ignoring reserved holes)."""
        return sum(f.n_bits for f in self._fields)

    def get_msb_pos(self) -> int:
        """MSB position of the highest field. The SV docstring notes
        the register either ends here (``BUS_DW - 1``) or has reserved
        bits beyond.
        """
        if not self._fields:
            return -1
        return max(f.msb_pos for f in self._fields)

    # -------------- access -----------------------------------------

    def read(self) -> int:
        """Read every field and pack them into a single word."""
        word = 0
        for f in self._fields:
            word |= (f.value & ((1 << f.n_bits) - 1)) << f.lsb_pos
        return word

    def write(self, word: int) -> None:
        """Write a single word, slicing it into the register's fields."""
        for f in self._fields:
            f.value = (word >> f.lsb_pos) & ((1 << f.n_bits) - 1)


class DVBaseRegBlock:
    """Block / "RAL model".

    Mirrors ``dv_base_reg_block``. ``build(base_addr)`` is left as a
    pseudo-pure-virtual: the base implementation raises ``RuntimeError``,
    matching the SV class which calls ``uvm_fatal``. Subclasses
    override it to populate themselves with concrete registers.
    """

    def __init__(self, name: str = "dv_base_reg_block") -> None:
        self.name = name
        self.base_addr: int = 0
        self._regs: Dict[str, DVBaseReg] = {}

    # -------------- construction -----------------------------------

    def add_reg(self, reg: DVBaseReg) -> None:
        if reg.name in self._regs:
            raise ValueError(f"Duplicate register name {reg.name!r}")
        self._regs[reg.name] = reg

    def get_reg_by_name(self, name: str) -> Optional[DVBaseReg]:
        return self._regs.get(name)

    @property
    def regs(self) -> List[DVBaseReg]:
        return list(self._regs.values())

    # -------------- pseudo-pure-virtual ----------------------------

    def build(self, base_addr: int = 0) -> None:
        """Build the block. Subclasses must override.

        SV equivalent calls ``uvm_fatal`` when invoked on the base
        directly; we raise to match that intent.
        """
        raise RuntimeError(
            f"{type(self).__name__}.build() is pseudo-pure-virtual; "
            "subclasses must override it to instantiate IP-specific registers."
        )

    # Optional: a place for the SV-style "reset all registers to their
    # reset value" helper. Not in the SV class but trivial to add and
    # often handy at the start of tests.
    def reset(self) -> None:
        for reg in self._regs.values():
            for f in reg.fields:
                f.value = f.reset
