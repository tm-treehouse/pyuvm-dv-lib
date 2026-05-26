# SPDX-License-Identifier: Apache-2.0
# Ported from OpenTitan hw/dv/sv/dv_lib (c) lowRISC contributors.
# See NOTICE for attribution.
"""
dv_report: A tiny analogue of OpenTitan's ``dv_report_server`` and
``dv_report_catcher``.

In the original library, ``dv_base_test::build_phase`` does:

    dv_report_server  m_dv_report_server = new();
    dv_report_catcher m_report_catcher;
    uvm_report_server::set_server(m_dv_report_server);
    `uvm_create_obj(dv_report_catcher, m_report_catcher)
    add_message_demotes(m_report_catcher);
    uvm_report_cb::add(null, m_report_catcher);

so that test pass/fail summaries are uniform across testbenches and individual
IPs can demote noisy false-positive messages without touching the source.

pyuvm exposes ``uvm_report_object`` and a logger, but it has no
``uvm_report_catcher`` and no pluggable report server. We instead provide:

* :class:`DVReportCatcher` — a small object the user can populate with
  ``(level, id_pattern) -> new_level`` rules. It's installed as a
  logging filter on pyuvm's logger, and does the demotion at log-time.
* :func:`install_dv_report_server` — installs the catcher and an error
  counter so the test can call ``server.summarize()`` at the end of run.

This module deliberately uses **standard stdlib :mod:`logging` levels**
(``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR`` / ``CRITICAL``) rather than
the SystemVerilog ``UVM_INFO`` / ``UVM_WARNING`` / ``UVM_ERROR`` /
``UVM_FATAL`` names. The mapping is:

    UVM severity  →  stdlib logging level
    UVM_INFO         logging.INFO       (20)
    UVM_WARNING      logging.WARNING    (30)
    UVM_ERROR        logging.ERROR      (40)
    UVM_FATAL        logging.CRITICAL   (50)

The :data:`LEVELS` tuple is the set of levels the catcher counts;
``DEBUG`` is also accepted in case a testbench uses it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Pattern, Tuple, Union


# Public type: anywhere we accept "a level", you can pass either a stdlib
# integer constant (``logging.WARNING``) or its canonical name as a string
# (``"WARNING"``). Lowercase names are accepted too.
Level = Union[int, str]


# Levels the catcher counts. DEBUG is included so debug-level messages
# aren't silently dropped from the summary; in practice OpenTitan's
# UVM_INFO maps onto everything at INFO and below.
LEVELS: Tuple[int, ...] = (
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
    logging.CRITICAL,
)


def _coerce_level(level: Level) -> int:
    """Normalise a stdlib level given as int or name to an int.

    Accepts e.g. ``logging.WARNING``, ``"WARNING"``, ``"warning"``,
    or ``30``. Raises ``ValueError`` for anything else.
    """
    if isinstance(level, int):
        if level not in LEVELS:
            # Allow custom levels too; we just can't usefully name them.
            return level
        return level
    if isinstance(level, str):
        # logging.getLevelName(name) returns the int for a known name,
        # or the string "Level <n>" if unknown. Filter the latter out.
        resolved = logging.getLevelName(level.upper())
        if isinstance(resolved, int):
            return resolved
    raise ValueError(f"Unknown logging level {level!r}")


@dataclass
class _DemoteRule:
    """A single id-regex -> new-level rule."""
    id_pattern: Pattern[str]
    from_level: Optional[int]   # None = match any source level
    to_level: int


@dataclass
class DVReportCatcher(logging.Filter):
    """User-facing catcher object.

    Mirrors the role of ``dv_report_catcher`` in dv_lib. Tests override
    :meth:`DVBaseTest.add_message_demotes` and call :meth:`add_demote` on
    the catcher passed in.
    """

    rules: List[_DemoteRule] = field(default_factory=list)
    counts: Dict[int, int] = field(
        default_factory=lambda: {lvl: 0 for lvl in LEVELS},
    )

    # logging.Filter wants __init__-without-args compatible kwargs; the
    # dataclass generates a workable __init__ for us, but logging.Filter's
    # own __init__ is not called. That's fine — Filter's only state is
    # `self.name`, used to scope filters, which we don't need.
    def __post_init__(self) -> None:  # pragma: no cover - trivial
        # Initialise the logging.Filter base. It accepts an empty `name`,
        # meaning "match everything".
        logging.Filter.__init__(self, name="")

    # ----- public API ---------------------------------------------------

    def add_demote(
        self,
        id_pattern: str,
        to_level: Level,
        from_level: Optional[Level] = None,
    ) -> None:
        """Register a demote rule.

        ``id_pattern`` is a regular expression matched against the message
        ID (or, lacking one, the full message). ``to_level`` is the new
        logging level — either an int (``logging.INFO``) or its name
        (``"INFO"``). ``from_level``, if given, restricts the rule to
        messages currently at that level.
        """
        to_int = _coerce_level(to_level)
        from_int = None if from_level is None else _coerce_level(from_level)
        self.rules.append(_DemoteRule(
            id_pattern=re.compile(id_pattern),
            from_level=from_int,
            to_level=to_int,
        ))

    def summarize(self) -> str:
        """Return a one-line summary of how many messages were seen at
        each level. Roughly equivalent to
        ``dv_report_server::report_summarize``.
        """
        parts = [
            f"{logging.getLevelName(lvl)}={self.counts[lvl]}"
            for lvl in LEVELS
        ]
        return "DV_REPORT_SUMMARY: " + " ".join(parts)

    @property
    def error_count(self) -> int:
        """Number of ``ERROR`` + ``CRITICAL`` messages observed
        (post-demotion). The SV equivalent counts UVM_ERROR + UVM_FATAL.
        """
        return (
            self.counts.get(logging.ERROR, 0)
            + self.counts.get(logging.CRITICAL, 0)
        )

    # ----- logging.Filter hook -----------------------------------------

    def filter(self, record: logging.LogRecord) -> bool:
        """Apply demote rules and bump counters. Always returns True so the
        record still propagates — we mutate it in place.
        """
        msg = str(record.getMessage())
        level = record.levelno

        for rule in self.rules:
            if rule.from_level is not None and rule.from_level != level:
                continue
            if rule.id_pattern.search(msg):
                level = rule.to_level
                record.levelno = level
                record.levelname = logging.getLevelName(level)
                break

        self.counts[level] = self.counts.get(level, 0) + 1
        return True


# Logger names we'll try, in order, when the caller doesn't pass one.
# Different pyuvm / cocotb versions log under different roots:
#   * pyuvm 4.x under cocotb: components log on "cocotb.<full_name>",
#   * pyuvm with the legacy "uvm.*" tree: components log on "uvm.<full_name>",
#   * pyuvm standalone:                    "pyuvm.<full_name>".
# Detection is best-effort; the caller can always pass ``logger_name=`` to
# pin it down explicitly.
_AUTO_LOGGER_CANDIDATES: Tuple[str, ...] = ("cocotb", "uvm", "pyuvm")


def _detect_logger_name() -> str:
    """Pick the most plausible root logger to attach the catcher to.

    We look for an existing :class:`logging.Logger` already in the manager
    that matches one of the known names *and* has at least one descendant
    or handler — i.e., something has been logging through it. If none
    look populated we fall back to the first candidate ("cocotb"), which
    is the right answer in the most common deployment.
    """
    manager = logging.Logger.manager
    populated: Dict[str, int] = {}
    # Score = number of descendants currently in the manager's dict +
    # number of handlers on the candidate itself. A populated tree is a
    # strong signal that *something* is logging there.
    for name in _AUTO_LOGGER_CANDIDATES:
        descendants = sum(
            1 for n in manager.loggerDict
            if n == name or n.startswith(name + ".")
        )
        handlers = len(logging.getLogger(name).handlers)
        populated[name] = descendants + handlers

    best = max(populated, key=lambda n: populated[n])
    if populated[best] == 0:
        # No tree looks alive yet; default to the cocotb root, which is
        # right under pyuvm-under-cocotb (the most common case).
        return _AUTO_LOGGER_CANDIDATES[0]
    return best


def install_dv_report_server(
    catcher: Optional[DVReportCatcher] = None,
    logger_name: Optional[str] = None,
) -> Tuple[DVReportCatcher, logging.Logger]:
    """Install ``catcher`` so it filters every record under ``logger_name``.

    This is the analogue of ``uvm_report_server::set_server`` +
    ``uvm_report_cb::add(null, m_report_catcher)`` in the original SV.

    Subtleties this function handles for you:

    1. **Auto-detect the right root.** If ``logger_name`` is ``None`` we
       look at which logger tree has descendants and/or handlers and
       attach there. Different deployments use different roots:
       ``cocotb`` (pyuvm under cocotb), ``uvm`` (some pyuvm versions),
       or ``pyuvm`` (standalone).

    2. **Walk both up AND down.** :class:`logging.Filter` on a logger
       only runs for records emitted on that logger; filters on
       handlers run for propagated records too — BUT pyuvm's
       per-component loggers are configured with ``propagate=False``
       and carry their *own* handler. That means records never reach
       ancestor handlers, so we also have to walk down into every
       descendant logger of the install root and attach the catcher to
       each one's handlers. Without that downward walk, records emitted
       by ``uvm.uvm_test_top.env.scoreboard`` (which doesn't propagate
       and has its own ``StreamHandler``) bypass the catcher entirely.

    3. **Belt-and-braces logger filter.** We also add ``catcher`` as a
       filter on the named logger itself, in case some record is
       emitted directly on it (rare, but it happens).

       Caveat: :class:`logging.NullHandler` deliberately skips the
       handler machinery — including filter execution — so attaching
       to a ``NullHandler`` is a no-op. If you're seeing zero counts,
       check that the chain has at least one real handler
       (``StreamHandler``, ``FileHandler``, ...) above the components.
       Under cocotb that's always the case.

    Important: call this **after** every component has been created
    (i.e. at the end of ``build_phase``), so the downward walk can see
    all the per-component loggers. If you call it earlier you'll miss
    components that don't exist yet — they won't get filtered.

    Idempotency: calling this function twice with the same catcher will
    not double-count, because :meth:`logging.Filterer.addFilter` is a
    no-op for an already-installed filter. Calling it with two
    *different* catchers leaves both installed (and counting), matching
    how the original SV code lets multiple catchers coexist.
    """
    if catcher is None:
        catcher = DVReportCatcher()

    if logger_name is None:
        logger_name = _detect_logger_name()

    logger = logging.getLogger(logger_name)
    seen_handlers: set = set()

    def attach_to_handlers(lg: logging.Logger) -> None:
        for h in lg.handlers:
            if id(h) in seen_handlers:
                continue
            seen_handlers.add(id(h))
            h.addFilter(catcher)

    # --- Walk UP the parent chain ---
    # Catches records that propagate from descendants and bubble through
    # handlers higher in the tree (typical pyuvm-under-cocotb case).
    lg: Optional[logging.Logger] = logger
    while lg is not None:
        attach_to_handlers(lg)
        if not lg.propagate:
            break
        lg = lg.parent

    # --- Walk DOWN into every descendant logger ---
    # Catches records emitted by per-component loggers that have their
    # own handler and propagate=False (which is how pyuvm sets up
    # `uvm.uvm_test_top.<...>` and similar trees). Without this, those
    # records never visit any handler that our catcher is on.
    #
    # We attach ONLY to the descendant's handlers, not as a
    # logger-filter on the descendant: a record emitted on a descendant
    # logger runs the logger's filters AND its handler's filters. If we
    # added the catcher in both places we'd double-count.
    manager = logging.Logger.manager
    prefix = "" if logger_name == "" else logger_name + "."
    for name in list(manager.loggerDict):
        if name == logger_name or name.startswith(prefix):
            descendant = logging.getLogger(name)
            attach_to_handlers(descendant)

    # Logger-level filter on the install root as a fallback.
    logger.addFilter(catcher)

    return catcher, logger


def reinstall_on_new_components(
    catcher: DVReportCatcher,
    logger_name: Optional[str] = None,
) -> int:
    """Re-walk the logger tree to pick up loggers/handlers created since
    the last install. Useful if components are constructed lazily after
    ``build_phase`` (rare in well-formed UVM testbenches, but pyuvm
    does occasionally create loggers on demand).

    Returns the number of handlers newly filtered.
    """
    if logger_name is None:
        logger_name = _detect_logger_name()
    added = 0
    manager = logging.Logger.manager
    prefix = "" if logger_name == "" else logger_name + "."
    for name in list(manager.loggerDict):
        if name == logger_name or name.startswith(prefix):
            descendant = logging.getLogger(name)
            for h in descendant.handlers:
                if catcher not in h.filters:
                    h.addFilter(catcher)
                    added += 1
    return added
