# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_base_seq_item: Base class for all sequence items in dv_lib testbenches.

The original SV class ``dv_base_seq_item`` (where present) extends
``uvm_sequence_item`` and gives every item a uniform ``convert2string`` /
``do_print`` story. We mirror that with a Python ``__str__`` that walks the
public attributes — pyuvm doesn't give items a free ``convert2string``
either, so this saves boilerplate in extended classes.

Implementation note: pyuvm's ``uvm_sequence_item.__init__`` installs a
number of *public* (non-underscore) bookkeeping attributes on the
instance — ``transaction_id``, ``start_condition``, ``finish_condition``,
``item_ready``, ``parent_sequence_id``, ``response_id``. These are UVM
infrastructure, not transaction payload, so we must exclude them from
``_state_dict``; otherwise ``do_compare`` would always fail (each item
has a unique ``transaction_id``) and ``do_copy`` would clobber the
machinery. :data:`_UVM_INTERNAL_ATTRS` lists them.
"""
from __future__ import annotations

from pyuvm import uvm_sequence_item


# Public attribute names that pyuvm's uvm_sequence_item sets for its own
# bookkeeping. They are not part of the transaction payload and must be
# excluded from copy / compare / string conversion.
_UVM_INTERNAL_ATTRS = frozenset({
    "transaction_id",
    "start_condition",
    "finish_condition",
    "item_ready",
    "parent_sequence_id",
    "response_id",
})


class DVBaseSeqItem(uvm_sequence_item):
    """Base sequence item. Extend this for IP-specific transactions."""

    def __init__(self, name: str = "dv_base_seq_item") -> None:
        super().__init__(name)

    # ------------------------------------------------------------------
    # SystemVerilog ``do_copy`` and ``do_compare`` map onto these dunders
    # in Python. We provide a sensible default that covers the common
    # case where every public attribute on the item is part of the
    # transaction state. Subclasses with non-data attributes should
    # override.
    # ------------------------------------------------------------------

    def _state_dict(self) -> dict:
        return {
            k: v for k, v in self.__dict__.items()
            if not k.startswith("_")
            and k != "name"
            and k not in _UVM_INTERNAL_ATTRS
        }

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        body = ", ".join(f"{k}={v!r}" for k, v in self._state_dict().items())
        return f"{type(self).__name__}({body})"

    def do_copy(self, rhs: "DVBaseSeqItem") -> None:
        """Mimic UVM ``do_copy``: copy public state from ``rhs`` into self."""
        for k, v in rhs._state_dict().items():
            setattr(self, k, v)

    def do_compare(self, rhs: "DVBaseSeqItem") -> bool:
        """Mimic UVM ``do_compare``: structural equality of public state."""
        return type(self) is type(rhs) and self._state_dict() == rhs._state_dict()
