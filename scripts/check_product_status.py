#!/usr/bin/env python3
"""Validate the canonical product-status block and its local evidence paths."""

from __future__ import annotations

import argparse
import ast
import binascii
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

START: Final = "<!-- product-status:v1:start -->"
END: Final = "<!-- product-status:v1:end -->"
REQUIRED_IDS: Final = ("AC-01", "AC-02", "AC-03", "CHUNK-SWEEP")
VALID_STATUSES: Final = frozenset({"COMPLETE", "INCOMPLETE"})
PATH_RE: Final = re.compile(r"`([^`]+)`")
DOCUMENT_START: Final = "<!-- product-evidence:v1:start -->"
DOCUMENT_END: Final = "<!-- product-evidence:v1:end -->"
EVIDENCE_CONTRACT: Final = {
    "AC-01": frozenset(
        {
            "tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy",
            "tests/test_staleness.py::test_count_cancellation_still_reports_semantic_staleness",
            "tests/test_staleness.py::test_same_stable_id_material_change_is_replacement",
            "tests/test_staleness.py::test_pending_count_is_computed_live_against_the_store",
        }
    ),
    "AC-02": frozenset(
        {
            "tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once",
            "tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively",
            "tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier",
            "tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped",
            "tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties",
            "tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas",
            "tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped",
        }
    ),
    "AC-03": frozenset(
        {
            "docs/FIRST-PACK-EVIDENCE.md",
            "tests/test_mcp_two_tier.py::test_get_entity_full_record",
            "tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface",
        }
    ),
    "CHUNK-SWEEP": frozenset(
        {"docs/CHUNK-SWEEP-2026-08.md", "scripts/sweep_chunk_size.py"}
    ),
}
TEST_EVIDENCE_DIGESTS: Final = {
    "tests/test_staleness.py::test_manifest_carries_basis_and_the_default_policy": "187ae53741bb61b723e528c0fed5974c67934271bbf23d17d54c09d2e2cbd2fd",
    "tests/test_staleness.py::test_count_cancellation_still_reports_semantic_staleness": "490117e7b1ed4ab83eb3e7b9fea014e292dd30a51a51c2efbbee77d41507949d",
    "tests/test_staleness.py::test_same_stable_id_material_change_is_replacement": "d39412c6b53cea442505fcc85e1953b313dd4a564f23cf9a5cf4b94cf03c60c3",
    "tests/test_staleness.py::test_pending_count_is_computed_live_against_the_store": "c879c14e71112fdc9eaa365aa134215fc3d7ede2aff53063d14f5c37ac9669ea",
    "tests/test_registry.py::test_absent_cache_is_off_not_an_error_and_warns_once": "c326eec4b610145db80a3d1b72becd69b32e1c772110be4f36ecff68ec515103",
    "tests/test_registry.py::test_csv_import_resolves_scientific_synonym_and_common_case_insensitively": "0ce6de484d535417956cb912e9c02e7f92678e6d0d4f4fdd9376369c62fa538f",
    "tests/test_agrochem_schema.py::test_organisms_and_actives_carry_their_registry_identifier": "5cb9fcfa261837e8668a0c8de2af08609fb3a7bc0c5a98aeb8bf9a484526988f",
    "tests/test_normalization.py::test_unresolved_organism_is_kept_flagged_and_model_code_is_dropped": "e796e76ec19ced125b07c9376ab1aab12785ea95cd40c30dee032a99d45ee40e",
    "tests/test_normalization.py::test_extraction_normalizes_before_storage_and_review_exposes_properties": "2b0c63e02f2ec11aeb4b4af4ae6a08b70aaba4ea67f8b75e05afb9ed933ca2dd",
    "tests/test_cas_normalization.py::test_alias_resolution_cache_authority_and_moa_follow_canonical_cas": "5426ba3764035bda5cc22050c74b7353eff60ac47a08fb42bef8288a826afb9d",
    "tests/test_cas_normalization.py::test_unknown_active_is_flagged_without_moa_and_model_cas_is_dropped": "5f4919c76a1300590de379f4e46f0fa34624a25ba0d5abbdb23de1f4748a8547",
    "tests/test_mcp_two_tier.py::test_get_entity_full_record": "d88dc1a163345101f58ab9615f923c69e5998b8a899dbaf041bccb327774b7a6",
    "tests/test_mcp_two_tier.py::test_fastmcp_exposes_two_tier_surface": "81899c9a0856c1515df3ef2fd90e16bc61a87c246c6ae069096152e823c94d75",
}
_UNSIGNED: Final = -1
SWEEP_DIGEST: Final = "66eacf5b9d57b4687d7f0b378871ea6885ad79fd68b4e9718e3dc8b06df7045f"
# The digests below bind two different things, and the difference is the point.
#
# TEST_EVIDENCE_DIGESTS pins the AST of each named evidence function: it answers "is
# this the body the spec claims". EVIDENCE_MODULE_DIGESTS pins the whole content of
# every non-product file on the evidence path: it answers "is this the world that body
# runs in". The second exists because a body's meaning lives in its free names, and
# those were previously resolved from the evidence module's live `__dict__` — so a
# module-level `def normalize_proposal(...)` shadowing the product import left all
# thirteen bodies byte-identical, every AST digest matching, and the receipt printing
# while normalization was a no-op.
#
# `ontologylab/**` is deliberately absent from both maps: it is the product under test,
# and pinning it would make the gate assert its own input. Everything else the child
# loads from the audited tree must be declared here, and the child re-checks the list
# against what actually loaded.
EVIDENCE_MODULE_DIGESTS: Final = {
    "tests/factories.py": "b2ee5b19a316920e95b775be055d2e015617cfdc11f2c6effb5b9a4840411d89",
    "tests/test_agrochem_schema.py": "f1131a56975b6c85f5e809292f074e3aa2a1b015e386ef9db0e6f0de7b9ab7ca",
    "tests/test_cas_normalization.py": "ce2748cf82aed53f3fe18a8b4d48485d8c84facf408005939546cd6837aa4951",
    "tests/test_mcp_two_tier.py": "7b188857344630992eccbd9cb6e5f919caa7a53bf021fb26e6203af15b6e727e",
    "tests/test_normalization.py": "4e246aba9d334f89c2533d3042c45cae8c5c07834c4a512980ad92786bb1056d",
    "tests/test_registry.py": "ddfb3ef255f72f4717fbf487c1c3af1c3ac6f001cd77666e10f38c387b81c4ba",
    "tests/test_staleness.py": "4718c614d0f5df94fc20a20ad8cade9e11622978179c0c17a684a94f2a853adf",
}
EVIDENCE_EXECUTOR_PROGRAM: Final = """
import ast
import hashlib
import hmac
import json
import os
import struct
import sys
import types
from pathlib import Path
from types import CodeType

# Under `-S` the interpreter has no site-packages on its path, so put back exactly the
# directories the parent resolved while `site` still worked -- and nothing else.
for _entry in os.environ.get("ONTOLOGYLAB_STATUS_SITEDIRS", "").split(os.pathsep):
    if _entry and Path(_entry).is_absolute() and _entry not in sys.path:
        sys.path.append(_entry)

ROOT = Path(sys.argv[1]).resolve()
PLAN = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
LEDGER_FILE = Path(sys.argv[3])
# DECLARED BOUNDARY (docs/PRODUCT_SPEC.md §7.1, case 1): this key is reachable as a global
# of this program's `__main__`, so product code committed specifically against this checker
# can read it and sign a forged report. That is out of scope by decision, not by oversight:
# anyone able to commit such a file can edit the acceptance table instead.
#
# Read the parent's per-run secret off an inherited pipe and close it immediately. The
# ledger and the receipt are both files at paths on this argv, so anything running in this
# process could write them; what it cannot do is produce this secret, because the pipe is
# drained and closed here, at import time, before any repository code has run. Everything
# that arrives later -- fixtures, product imports, `atexit` -- finds a closed descriptor.
_secret_fd = int(sys.argv[4])
SECRET = os.read(_secret_fd, 64)
# Closing is hygiene, not the barrier: the parent already closed the write end and this
# read consumed the whole secret, so a later reader gets b"" either way. The barrier is
# that no code runs before this point -- see `-I -S` on the command line.
os.close(_secret_fd)
if len(SECRET) != 64:
    raise SystemExit("evidence executor did not receive its run secret")
import pytest

NODES = PLAN["nodes"]
MODULES = PLAN["modules"]
PRODUCT = ROOT / "ontologylab"
# DECLARED BOUNDARY (docs/PRODUCT_SPEC.md §7.1, case 3): what is on this list is exempt from
# content verification, so a tampered installed dependency (pytest, pluggy) is not detected
# here. Out of scope by decision; see the spec for why the boundary sits there.
#
# The library boundary is stated explicitly rather than derived from `sys.prefix`, which
# collapses to the base interpreter under `-S` and previously exempted an in-tree
# virtualenv by accident. These are the directories the parent resolved and handed over,
# plus the interpreter's own; everything else under the audited root is repository code.
LIBRARY_ROOTS = tuple(
    dict.fromkeys(
        Path(entry).resolve()
        for entry in (
            *os.environ.get("ONTOLOGYLAB_STATUS_SITEDIRS", "").split(os.pathsep),
            sys.base_prefix,
            sys.prefix,
        )
        # Absolute directories only, checked here as well as where the value is produced:
        # "" and "." mean the working directory, which is the audited root, and accepting
        # either would exempt the whole repository from the audit that follows.
        if entry and Path(entry).is_absolute() and Path(entry).is_dir()
    )
)
# And whatever it is spelled as, the audited tree is not a library. Redundant in practice --
# the static content gate rejects a tampered evidence file before the child runs, so no test
# fails when this line is removed -- but the library list is otherwise an outside-controlled
# way to narrow the audit, and that is worth refusing on principle rather than on coverage.
LIBRARY_ROOTS = tuple(root for root in LIBRARY_ROOTS if root != ROOT)
LEDGER = {"executed": {}, "modules": {}, "unaudited": [], "product": {}, "substituted": []}
# Which method names `@dataclass` is allowed to synthesise, per decorator argument. The
# decorator's own arguments decide: `frozen=True` is what permits `__setattr__`/`__delattr__`,
# `order=True` the comparisons, and so on. A name is only ever exempt when the *source* shows
# a dataclass-decorated class that does not define it in its own body.
DATACLASS_GENERATED = {
    "init": ("__init__",),
    "repr": ("__repr__",),
    "eq": ("__eq__",),
    "order": ("__lt__", "__le__", "__gt__", "__ge__"),
    "frozen": ("__setattr__", "__delattr__"),
    "unsafe_hash": ("__hash__",),
    "match_args": ("__match_args__",),
}
# `eq=True` with `frozen=True` also synthesises `__hash__`; dataclasses documents this.
DATACLASS_DEFAULTS = {
    "init": True,
    "repr": True,
    "eq": True,
    "order": False,
    "frozen": False,
    "unsafe_hash": False,
}
# Every source file this interpreter compiles, recorded by an audit hook installed before
# anything else runs. Walking `sys.modules` was evadable two ways that both keep working
# code off the list -- `del sys.modules[name]` after import, and `exec` of a file that never
# becomes a module at all. An audit hook sees the compile itself, and once installed it
# cannot be removed (there is no public API to drop one), so the record is append-only.
COMPILED_FILES = set()


def _record_compile(event, arguments):
    if event == "compile" and len(arguments) > 1 and arguments[1]:
        COMPILED_FILES.add(str(arguments[1]))
    elif event == "exec" and arguments:
        origin = getattr(arguments[0], "co_filename", None)
        if origin:
            COMPILED_FILES.add(str(origin))


sys.addaudithook(_record_compile)

# The audited definitions are compiled here rather than by pytest's assertion
# rewriter, so plain `assert` enforcement is what carries the evidence.
if sys.flags.optimize:
    raise SystemExit("canonical evidence cannot run with assertions optimized out")


def audited_source(relative):
    # Read a covered file and hold its whole content to the declared digest.
    expected = MODULES.get(relative)
    if expected is None:
        raise AssertionError(f"{relative}: no declared module digest")
    data = (ROOT / relative).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise AssertionError(f"{relative}: module digest {actual} != {expected}")
    LEDGER["modules"][relative] = actual
    return data.decode("utf-8")


VERIFIED_NAMESPACES = {}


def verified_namespace(relative):
    # Globals for the audited bodies, produced by executing the verified source of
    # their own module. pytest's imported copy of that module is never consulted.
    namespace = VERIFIED_NAMESPACES.get(relative)
    if namespace is None:
        source = audited_source(relative)
        path = str(ROOT / relative)
        namespace = {
            "__name__": f"_audited_{relative.replace('/', '_')[:-3]}",
            "__file__": path,
            "__builtins__": __builtins__,
        }
        exec(compile(source, path, "exec"), namespace)
        VERIFIED_NAMESPACES[relative] = namespace
    return namespace


def audited_definition(node_id):
    # Return the definition whose AST digest is the audited one, or fail loudly.
    entry = NODES[node_id]
    source = audited_source(entry["path"])
    tree = ast.parse(source, filename=entry["path"])
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != entry["name"]:
            continue
        dumped = ast.dump(node, annotate_fields=True, include_attributes=False)
        if hashlib.sha256(dumped.encode("utf-8")).hexdigest() == entry["digest"]:
            matches.append(node)
    if len(matches) != 1:
        raise AssertionError(
            f"{node_id}: {len(matches)} definitions carry the audited digest"
        )
    definition = matches[0]
    if definition.decorator_list:
        raise AssertionError(f"{node_id}: audited definition is decorated")
    if isinstance(definition, ast.AsyncFunctionDef):
        raise AssertionError(f"{node_id}: audited definition is async")
    signature = definition.args
    if (
        signature.posonlyargs
        or signature.kwonlyargs
        or signature.vararg
        or signature.kwarg
        or signature.defaults
    ):
        raise AssertionError(f"{node_id}: audited signature is not plain fixtures")
    return definition, entry


def module_origin(module):
    # A module's origin, from `__file__` or from the spec it was loaded with. A loader that
    # supplies neither is not thereby exempt: it is reported, because an evidence path made
    # of modules that decline to say where they came from is not auditable.
    origin = getattr(module, "__file__", None)
    if origin:
        return origin, True
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None) if spec is not None else None
    if origin and origin not in {"built-in", "frozen"}:
        return origin, True
    name = getattr(module, "__name__", "") or ""
    if name == "ontologylab" or name.startswith("ontologylab."):
        return None, False
    return None, True


def _frame(tag, payload):
    # A tag says what a value is; a fixed-width length says exactly where it ends. Concatenated
    # values therefore cannot collide through punctuation, repr formatting, or nesting.
    return tag + len(payload).to_bytes(8, "big") + payload


def _constant_bytes(value, ancestry=()):
    # The compiler's scalar domain, plus the containers CodeType.replace accepts in tests and
    # tooling. Exact type checks keep bool distinct from int. IEEE bytes preserve every float
    # distinction Python can observe, including signed zero and NaN sign/payload bits.
    value_type = type(value)
    if value is None:
        return _frame(b"N", b"")
    if value is Ellipsis:
        return _frame(b"E", b"")
    if value_type is bool:
        return _frame(b"B", b"1" if value else b"0")
    if value_type is int:
        return _frame(b"I", str(value).encode("ascii"))
    if value_type is float:
        return _frame(b"F", struct.pack(">d", value))
    if value_type is complex:
        return _frame(b"C", struct.pack(">dd", value.real, value.imag))
    if value_type is str:
        return _frame(b"S", value.encode("utf-8"))
    if value_type is bytes:
        return _frame(b"Y", value)
    if any(identity == id(value) for identity in ancestry):
        raise ValueError("cyclic code constant")
    descendants = (*ancestry, id(value))
    if value_type is tuple:
        return _frame(
            b"T", b"".join(_constant_bytes(item, descendants) for item in value)
        )
    if value_type is list:
        return _frame(
            b"L", b"".join(_constant_bytes(item, descendants) for item in value)
        )
    if value_type in {set, frozenset}:
        items = sorted(_constant_bytes(item, descendants) for item in value)
        return _frame(b"R" if value_type is frozenset else b"Q", b"".join(items))
    if value_type is dict:
        items = sorted(
            _frame(
                b"P",
                _constant_bytes(key, descendants)
                + _constant_bytes(item, descendants),
            )
            for key, item in value.items()
        )
        return _frame(b"D", b"".join(items))
    if value_type is CodeType:
        return _frame(b"K", _code_bytes(value, descendants))
    raise TypeError(
        "unsupported code constant: "
        f"{value_type.__module__}.{value_type.__qualname__}"
    )


def dataclass_aliases(tree):
    # Local names that refer to `dataclasses.dataclass` in this file, so that
    # `from dataclasses import dataclass as _dc` is recognised as the decorator it is.
    aliases = {"dataclass", "dataclasses.dataclass"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "dataclasses":
            for alias in node.names:
                if alias.name == "dataclass":
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "dataclasses" and alias.asname:
                    aliases.add(f"{alias.asname}.dataclass")
    return aliases


def dataclass_generated_names(tree):
    # Names each dataclass-decorated class in this source may have synthesised, read off the
    # class declaration rather than off the attribute name. A class the source does not
    # decorate generates nothing, so a `<string>` method on it is a leftover, not library
    # output -- which is the whole difference between proving provenance and matching a name.
    generated = {}
    aliases = dataclass_aliases(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        options = None
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if isinstance(target, ast.Attribute):
                name = f"{getattr(target.value, 'id', '')}.{target.attr}"
            else:
                name = getattr(target, "id", None)
            if name not in aliases:
                continue
            options = dict(DATACLASS_DEFAULTS)
            if isinstance(decorator, ast.Call):
                for keyword in decorator.keywords:
                    if keyword.arg in options and isinstance(keyword.value, ast.Constant):
                        options[keyword.arg] = bool(keyword.value.value)
        if options is None:
            continue
        allowed = set()
        for option, names in DATACLASS_GENERATED.items():
            if options.get(option, False):
                allowed.update(names)
        if options["eq"] and options["frozen"]:
            allowed.add("__hash__")
        if options["eq"] and not options["unsafe_hash"] and not options["frozen"]:
            allowed.add("__hash__")
        # A method the class body defines itself is written, not generated: dataclasses
        # leaves it alone, so it must come from this file like any other definition.
        written = {
            member.name
            for member in node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        generated[node.name] = allowed - written
    return generated


def regenerated_matches(module, class_node, attribute, code):
    # Provenance by re-derivation. Declaring the class a dataclass is necessary but not
    # sufficient: a leftover can target a real dataclass on a name that dataclass does
    # generate. So regenerate it -- execute only that class definition, in a copy of the
    # module's own namespace, and compare fingerprints. Only the class statement runs, so a
    # trailing `Cls.__repr__ = ...` in the same file cannot launder itself into the result.
    if class_node is None:
        return False
    namespace = dict(vars(module))
    try:
        exec(
            compile(
                ast.Module(body=[class_node], type_ignores=[]), "<regenerated>", "exec"
            ),
            namespace,
        )
        regenerated = vars(namespace[class_node.name]).get(attribute)
    except Exception:
        return False
    target = getattr(regenerated, "__func__", regenerated)
    reference = getattr(target, "__code__", None)
    if reference is None:
        return False
    return code_fingerprint(reference) == code_fingerprint(code)


def _code_bytes(code, ancestry=()):
    # Line tables and filenames describe placement, not meaning. Every semantic field retained
    # by the prior fingerprint is encoded through the same typed, length-delimited format, and
    # nested code objects recurse through this function rather than falling back to repr.
    fields = (
        code.co_name,
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_flags,
        code.co_code,
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_consts,
    )
    return _constant_bytes(fields, ancestry)


def code_fingerprint(code):
    # The digest is deterministic across processes and hash seeds because unordered values are
    # sorted by their complete canonical byte encoding before framing.
    return hashlib.sha256(_code_bytes(code)).hexdigest()


def literal_assignments(source, filename):
    # Module-level `NAME = <literal>` bindings, as the file declares them.
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return {}
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target] if node.value is not None else []
            value = node.value
        else:
            continue
        if not targets:
            continue
        # `frozenset({...})` and `set([...])` are Calls, not literals, and they are how this
        # product spells most of its lookup tables; evaluate those too, from the literal
        # argument only.
        node_value = value
        wrapper = None
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"frozenset", "set", "tuple", "list", "dict"}
            and not value.keywords
            and len(value.args) <= 1
        ):
            wrapper = {
                "frozenset": frozenset,
                "set": set,
                "tuple": tuple,
                "list": list,
                "dict": dict,
            }[value.func.id]
            node_value = value.args[0] if value.args else ast.Constant(value=())
        try:
            evaluated = ast.literal_eval(node_value)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            continue
        if wrapper is not None:
            try:
                evaluated = wrapper(evaluated)
            except (TypeError, ValueError):
                continue
        for target in targets:
            found[target.id] = evaluated
    return found


def live_code_objects(module):
    # Every binding path is walked independently. The second path in each result is the source
    # binding a descriptor decorates: `Owner.marker.callback` is explicit live ownership, while
    # `Owner.marker` is the qualified name compiling that declaration must produce.
    name = getattr(module, "__name__", None)
    for attribute, value in sorted(vars(module).items(), key=lambda item: item[0]):
        yield from _code_objects_of(attribute, value, name, ())


def _descriptor_members(value):
    # Read descriptor-owned state without calling its __get__, custom __getattribute__, or a
    # property. Ordinary instance dictionaries are obtained through the interpreter's concrete
    # __dict__ getset descriptor; user slots are concrete member descriptors. The traversal
    # boundary is this static state plus nested built-in containers -- arbitrary referenced
    # objects are not opened, so this cannot turn into an external object-graph crawl.
    descriptor_type = type(value)
    if not any(
        name in vars(base)
        for base in descriptor_type.__mro__
        for name in ("__get__", "__set__", "__delete__")
    ):
        return ()
    found = {}
    for base in descriptor_type.__mro__:
        namespace = vars(base)
        dictionary_descriptor = namespace.get("__dict__")
        if isinstance(dictionary_descriptor, types.GetSetDescriptorType):
            try:
                state = dictionary_descriptor.__get__(value, descriptor_type)
            except AttributeError:
                state = None
            if type(state) is dict:
                found.update(state)
        for attribute, slot in namespace.items():
            if (
                isinstance(slot, types.MemberDescriptorType)
                and attribute not in {"__dict__", "__weakref__"}
                and attribute not in found
            ):
                try:
                    found[attribute] = slot.__get__(value, descriptor_type)
                except AttributeError:
                    continue
    return tuple(sorted(found.items(), key=lambda item: item[0]))


def _code_objects_of(
    prefix,
    value,
    module_name,
    ancestry,
    source_binding=None,
    descriptor_owned=False,
):
    # Cycle prevention is per binding path, so aliases remain visible while a descriptor state
    # dictionary that points back to itself terminates. Only descriptor-owned built-in
    # containers are opened; module globals and arbitrary referenced objects are not crawled.
    if any(identity == id(value) for identity in ancestry):
        return
    descendants = (*ancestry, id(value))
    if isinstance(value, (types.FunctionType, types.MethodType)):
        code = value.__code__
        if value.__module__ == module_name:
            yield prefix, source_binding or prefix, code
        return
    if isinstance(value, type) and getattr(value, "__module__", None) == module_name:
        for attribute, member in sorted(vars(value).items(), key=lambda item: item[0]):
            binding = f"{prefix}.{attribute}"
            yield from _code_objects_of(
                binding, member, module_name, descendants, binding
            )
        return
    members = _descriptor_members(value)
    if members:
        declared_binding = source_binding or prefix
        for attribute, member in members:
            yield from _code_objects_of(
                f"{prefix}.{attribute}",
                member,
                module_name,
                descendants,
                declared_binding,
                True,
            )
        return
    if descriptor_owned and type(value) in {list, tuple}:
        for index, member in enumerate(value):
            yield from _code_objects_of(
                f"{prefix}[{index}]",
                member,
                module_name,
                descendants,
                source_binding,
                True,
            )
    elif descriptor_owned and type(value) is dict:
        for key, member in value.items():
            if type(key) not in {str, bytes, int, float, bool, type(None)}:
                raise TypeError(
                    "unsupported descriptor-state key: "
                    f"{type(key).__module__}.{type(key).__qualname__}"
                )
            yield from _code_objects_of(
                f"{prefix}[{key!r}]",
                member,
                module_name,
                descendants,
                source_binding,
                True,
            )


def product_identity():
    # What product did the bodies actually call?
    #
    # `ontologylab/**` is exempt from content pinning on purpose: it is the thing under
    # test, and pinning it would make the gate assert its own input. But the exemption was
    # doing more work than that. `verified_namespace` re-executes the evidence module's
    # source, so its `from ontologylab.x import y` reads a LIVE module attribute -- which
    # product code is free to rebind. A product module that detected the audit and re-execed
    # its own pre-mutation source put the good implementation in front of the audited bodies
    # while shipping the broken one.
    #
    # So this reports identity, not correctness: for every function a product module
    # exposes as its own, the code object must be one that compiling that module's current
    # source can produce. That is falsifiable without asserting anything about behaviour, it
    # is recorded inside the signed payload where in-child code cannot author it, and it is
    # not circular -- the product still gets to be as broken as it likes, it just cannot be
    # one thing on disk and another at call time.
    digests = {}
    substitutions = []
    for module in list(sys.modules.values()):
        origin, accountable = module_origin(module)
        if origin is None:
            if not accountable:
                substitutions.append(
                    f"{getattr(module, '__name__', '?')}: loaded with no declared origin"
                )
            continue
        path = Path(origin).resolve()
        if not (PRODUCT == path.parent or PRODUCT in path.parents):
            continue
        relative = path.relative_to(ROOT).as_posix()
        try:
            source = path.read_bytes()
        except OSError:
            substitutions.append(f"{relative}: unreadable")
            continue
        digests[relative] = hashlib.sha256(source).hexdigest()
        try:
            compiled = compile(source, str(path), "exec")
        except SyntaxError:
            substitutions.append(f"{relative}: will not compile")
            continue
        # Index every code object the file can produce, keyed by qualified name. Keying by
        # name is what makes this a binding rather than a lookup: a function rebound to a
        # different function *from the same file* used to pass, because the old check asked
        # only whether the bytecode appeared anywhere in the file.
        try:
            module_tree = ast.parse(source, filename=str(path))
            generated_by_dataclass = dataclass_generated_names(module_tree)
            class_nodes = {
                node.name: node
                for node in ast.walk(module_tree)
                if isinstance(node, ast.ClassDef)
            }
        except SyntaxError:
            generated_by_dataclass = {}
            class_nodes = {}
        producible = {}
        pending = [compiled]
        while pending:
            code = pending.pop()
            producible.setdefault(code.co_qualname, set()).add(code_fingerprint(code))
            pending.extend(
                const for const in code.co_consts if isinstance(const, CodeType)
            )
        # Module-level data. A rebound constant or a swapped lookup table is the same
        # accident as a rebound function, and the code-object rule cannot see it. Every
        # module-level name whose assignment in the file is a literal is compared against
        # that literal. Values derived from an expression -- a call, an attribute lookup, a
        # name, arithmetic -- are not statically knowable and are left unbound. That residual
        # is a limit of the analysis, not one of the three checker-targeting exclusions, and
        # is declared as such in docs/PRODUCT_SPEC.md §7.1.1.
        for attribute, expected in literal_assignments(source, str(path)).items():
            if attribute not in vars(module):
                continue
            live = vars(module)[attribute]
            if type(live) is not type(expected) or live != expected:
                substitutions.append(
                    f"{relative}::{attribute} does not hold the value this file assigns"
                )
        for binding, qualname, code in live_code_objects(module):
            origin = code.co_filename
            # Compiler-generated methods, narrowly. `@dataclass` compiles exactly these
            # dunders with the filename "<string>", and they genuinely do not exist in the
            # source, so they cannot be re-derived from it. Exempting *every* synthetic
            # origin was far wider than that: an ordinary leftover binding a product name to
            # `exec`/`eval`/`compile(..., "<string>", ...)` output inherited the same pass.
            # Anything else claiming a synthetic origin is reported under its binding path.
            if origin.startswith("<") and origin.endswith(">"):
                owner, _, attribute = qualname.rpartition(".")
                permitted = generated_by_dataclass.get(owner, frozenset())
                if (
                    origin == "<string>"
                    and attribute in permitted
                    and regenerated_matches(module, class_nodes.get(owner), attribute, code)
                ):
                    continue
                substitutions.append(
                    f"{relative}::{binding} was compiled from {origin}"
                )
                continue
            if any(
                library in Path(origin).resolve().parents
                for library in LIBRARY_ROOTS
                if Path(origin).is_absolute()
            ):
                continue
            if origin != str(path):
                substitutions.append(
                    f"{relative}::{binding} claims {origin}"
                )
            elif code_fingerprint(code) not in producible.get(qualname, frozenset()):
                substitutions.append(
                    f"{relative}::{binding} is not compiled from this file under that name"
                )
    return digests, sorted(set(substitutions))


def unaudited_repository_modules():
    # Every repository-local module that loaded, minus the product under test.
    found = []
    for origin in sorted(COMPILED_FILES):
        # Synthetic names, not paths: `<string>`, `<attrs generated ...>`, and the like.
        # These carry no filesystem claim to check, and libraries produce them constantly.
        if origin.startswith("<") and origin.endswith(">"):
            continue
        try:
            # Relative filenames are resolved against the audited root, which is this
            # process's cwd: `compile(source, "helper.py", ...)` names a real file there.
            candidate = Path(origin)
            path = (candidate if candidate.is_absolute() else ROOT / candidate).resolve()
        except (OSError, ValueError):
            continue
        if ROOT not in path.parents:
            continue
        if not path.is_file():
            # Code executed under a filename that does not exist: a `.pyc` with no adjacent
            # source fires no `compile` event and registers no module, but executing it does
            # fire `exec`, and the name it claims is unverifiable. Report rather than skip.
            if not any(library in path.parents for library in LIBRARY_ROOTS):
                found.append(f"{path.relative_to(ROOT).as_posix()}: claimed source is absent")
            continue
        if any(library in path.parents for library in LIBRARY_ROOTS):
            continue
        if PRODUCT == path.parent or PRODUCT in path.parents:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if MODULES.get(relative) != hashlib.sha256(path.read_bytes()).hexdigest():
            found.append(relative)
    for module in list(sys.modules.values()):
        origin, accountable = module_origin(module)
        if origin is None:
            if not accountable:
                found.append(f"{getattr(module, '__name__', '?')}: no declared origin")
            continue
        path = Path(origin).resolve()
        if ROOT not in path.parents:
            continue
        if any(library in path.parents for library in LIBRARY_ROOTS):
            continue
        if PRODUCT == path.parent or PRODUCT in path.parents:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if MODULES.get(relative) != hashlib.sha256(path.read_bytes()).hexdigest():
            found.append(relative)
    return sorted(set(found))


class EvidenceExecutor:
    # Execute the audited source itself, in globals built from audited source.

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_call(self, item):
        node_id = f"{item.path.resolve().relative_to(ROOT).as_posix()}::{item.originalname}"
        definition, entry = audited_definition(node_id)
        namespace = dict(verified_namespace(entry["path"]))
        module = ast.Module(body=[definition], type_ignores=[])
        exec(compile(module, str(ROOT / entry["path"]), "exec"), namespace)
        audited = namespace[entry["name"]]
        arguments = {
            argument.arg: item._request.getfixturevalue(argument.arg)
            for argument in definition.args.args
        }
        result = audited(**arguments)
        if result is not None:
            raise AssertionError("canonical test returned a value")
        LEDGER["executed"][node_id] = entry["digest"]
        item.runtest = lambda: None

    def pytest_sessionfinish(self):
        # Declared coverage is only worth anything if every declared file was really
        # checked, so re-read the ones no audited body happened to read directly.
        for relative in MODULES:
            if relative not in LEDGER["modules"]:
                audited_source(relative)
        LEDGER["unaudited"] = unaudited_repository_modules()
        LEDGER["product"], LEDGER["substituted"] = product_identity()


def write_report(code):
    # The exit code travels inside the authenticated payload. `os._exit` can still hand
    # the parent a zero, but it cannot make the parent believe a zero it did not sign.
    LEDGER["returncode"] = code
    payload = json.dumps(LEDGER, sort_keys=True)
    signature = hmac.new(SECRET, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    LEDGER_FILE.write_text(
        json.dumps({"payload": payload, "signature": signature}), encoding="utf-8"
    )


sys.path.insert(0, str(ROOT))
code = 70
try:
    code = pytest.main(sys.argv[5:], plugins=[EvidenceExecutor()])
finally:
    write_report(code)
raise SystemExit(code)
"""
DOCUMENT_CONTRACTS: Final = {
    "docs/FIRST-PACK-EVIDENCE.md": {
        "claims": [
            "sourced_entity_lookup",
            "sourced_relation_traversal",
            "full_entity_provenance",
            "live_staleness",
        ],
        "command": ".venv/bin/python -m ontologylab.mcp_server --packs-dir <throwaway>/packs --live-store <throwaway>/data/kg.sqlite",
        "evidence_id": "AC-03-FIRST-PACK",
        "kind": "recorded-execution",
        "result": {
            "content_hash": "sha256:eb233081b580a9100f08a17a4709223a9c05649607ad2848f4b6686f1e430449",
            "edges_verified": 28,
            "nodes_verified": 29,
            "pack_id": "agrochem-first-20260802-223925",
            "pending_verified_count": 1,
        },
    },
    "docs/CHUNK-SWEEP-2026-08.md": {
        "command": ".venv/bin/python scripts/sweep_chunk_size.py --engine claude --output-dir /tmp/ontologylab-chunk-sweep-2026-08",
        "decision": 3000,
        "evidence_id": "CHUNK-SWEEP-2026-08",
        "fixture": "tests/gold/agrochem-mini/docs.json",
        "kind": "recorded-measurement",
        "results": {
            "1500": {"calls": 10, "triple_f1": 0.9643},
            "3000": {"calls": 5, "triple_f1": 0.9818},
        },
        "sizes": [1500, 3000],
    },
}


@dataclass(frozen=True, slots=True)
class StatusEntry:
    item_id: str
    status: str
    evidence: tuple[str, ...]
    follow_up: str
    follow_up_detail: str


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    item_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class StatusReport:
    ok: bool
    entries: tuple[StatusEntry, ...]
    resolved_paths: tuple[str, ...]
    issues: tuple[Issue, ...]

    def payload(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "entries": [asdict(entry) for entry in self.entries],
            "resolved_paths": list(self.resolved_paths),
            "issues": [
                {"code": issue.code, "id": issue.item_id, "detail": issue.detail}
                for issue in self.issues
            ],
        }


def _table_rows(text: str) -> tuple[list[dict[str, str]], list[Issue]]:
    if text.count(START) != 1 or text.count(END) != 1:
        return [], [Issue("missing_delimiters", "DOCUMENT", "expected one v1 status block")]
    block = text.split(START, 1)[1].split(END, 1)[0]
    lines = [line.strip() for line in block.splitlines() if line.strip().startswith("|")]
    if len(lines) < 3:
        return [], [Issue("invalid_table", "DOCUMENT", "status block has no data rows")]
    headers = [cell.strip() for cell in lines[0].strip("|").split("|")]
    expected = ["ID", "Status", "Evidence", "Follow-up"]
    if headers != expected:
        return [], [
            Issue("invalid_table", "DOCUMENT", f"expected columns {', '.join(expected)}")
        ]
    rows: list[dict[str, str]] = []
    issues: list[Issue] = []
    for line_number, line in enumerate(lines[2:], start=3):
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            issues.append(
                Issue("invalid_table", f"ROW-{line_number}", "row width differs from header")
            )
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows, issues


def _follow_up(cell: str) -> tuple[str, str] | None:
    if cell == "NONE":
        return "NONE", ""
    for kind in ("BLOCKING", "NON-BLOCKING"):
        prefix = f"{kind}:"
        if cell.startswith(prefix) and cell[len(prefix) :].strip():
            return kind, cell[len(prefix) :].strip()
    return None


def _inside_root(root: Path, reference: str) -> Path | None:
    candidate = (root / reference).resolve()
    if candidate == root or root in candidate.parents:
        return candidate
    return None


def _module_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _evidence_path_issues(root: Path) -> list[Issue]:
    """Hold every non-product file on the evidence path to its declared content.

    The AST digests cover thirteen function bodies. These cover the modules those
    bodies live in and the helper module they import, because a body's free names —
    the product symbols it calls and the local helpers that build its inputs — are
    resolved out of that file's own namespace, not out of the hashed function node.
    """
    issues: list[Issue] = []
    for relative, expected in sorted(EVIDENCE_MODULE_DIGESTS.items()):
        candidate = _inside_root(root, relative)
        if candidate is None or not candidate.is_file():
            issues.append(Issue("evidence_module_missing", "DOCUMENT", relative))
        elif _module_digest(candidate) != expected:
            issues.append(Issue("evidence_module_integrity", "DOCUMENT", relative))
    declared = {node_id.split("::", 1)[0] for node_id in TEST_EVIDENCE_DIGESTS}
    uncovered = sorted(declared - set(EVIDENCE_MODULE_DIGESTS))
    if uncovered:
        issues.append(
            Issue("evidence_module_missing", "DOCUMENT", f"undeclared: {uncovered}")
        )
    contracted = {
        reference
        for references in EVIDENCE_CONTRACT.values()
        for reference in references
        if "::" in reference
    }
    if set(TEST_EVIDENCE_DIGESTS) != contracted:
        detail = (
            f"digest set != contract set: "
            f"missing={sorted(contracted - set(TEST_EVIDENCE_DIGESTS))}; "
            f"unexpected={sorted(set(TEST_EVIDENCE_DIGESTS) - contracted)}"
        )
        issues.append(Issue("evidence_contract", "DOCUMENT", detail))
    return issues


def _test_digest(path: Path, function_name: str) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return None
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function is None:
        return None
    normalized = ast.dump(function, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _documentary_evidence(path: Path, reference: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if text.count(DOCUMENT_START) != 1 or text.count(DOCUMENT_END) != 1:
        return False
    payload_text = text.split(DOCUMENT_START, 1)[1].split(DOCUMENT_END, 1)[0].strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return False
    return payload == DOCUMENT_CONTRACTS[reference]


def _sweep_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def check_status(document: Path, root: Path) -> StatusReport:
    root = root.resolve()
    document = document if document.is_absolute() else root / document
    try:
        text = document.read_text(encoding="utf-8")
    except OSError as exc:
        issue = Issue("unreadable_document", "DOCUMENT", str(exc))
        return StatusReport(False, (), (), (issue,))

    rows, issues = _table_rows(text)
    if not rows and issues:
        return StatusReport(False, (), (), tuple(issues))
    entries: list[StatusEntry] = []
    resolved_paths: set[str] = set()
    counts = {item_id: 0 for item_id in REQUIRED_IDS}

    for row in rows:
        item_id = row["ID"]
        status = row["Status"]
        evidence = tuple(PATH_RE.findall(row["Evidence"]))
        parsed_follow_up = _follow_up(row["Follow-up"])

        if item_id not in counts:
            issues.append(Issue("unexpected_id", item_id, "ID is not in the canonical set"))
        else:
            counts[item_id] += 1
        if status not in VALID_STATUSES:
            issues.append(Issue("invalid_status", item_id, status))
        elif status != "COMPLETE":
            issues.append(
                Issue("stale_status", item_id, f"expected COMPLETE, got {status}")
            )
        if not evidence:
            issues.append(Issue("empty_evidence", item_id, "at least one path is required"))
        expected_evidence = EVIDENCE_CONTRACT.get(item_id)
        if expected_evidence is not None and set(evidence) != expected_evidence:
            missing = sorted(expected_evidence - set(evidence))
            unexpected = sorted(set(evidence) - expected_evidence)
            detail = f"missing={missing}; unexpected={unexpected}"
            issues.append(Issue("evidence_contract", item_id, detail))
        if parsed_follow_up is None:
            issues.append(
                Issue("invalid_followup", item_id, "use NONE, BLOCKING:, or NON-BLOCKING:")
            )
            follow_up, follow_up_detail = "INVALID", row["Follow-up"]
        else:
            follow_up, follow_up_detail = parsed_follow_up
        if status == "COMPLETE" and follow_up == "BLOCKING":
            issues.append(
                Issue(
                    "followup_contradiction",
                    item_id,
                    "COMPLETE cannot have a blocking follow-up",
                )
            )
        if status == "INCOMPLETE" and follow_up != "BLOCKING":
            issues.append(
                Issue(
                    "followup_contradiction",
                    item_id,
                    "INCOMPLETE requires a blocking follow-up",
                )
            )

        for reference in evidence:
            path_reference, separator, function_name = reference.partition("::")
            candidate = _inside_root(root, path_reference)
            if candidate is None or not candidate.is_file():
                issues.append(Issue("broken_path", item_id, path_reference))
                continue
            resolved_paths.add(path_reference)
            if separator:
                expected_digest = TEST_EVIDENCE_DIGESTS.get(reference)
                if expected_digest is None or _test_digest(candidate, function_name) != expected_digest:
                    issues.append(Issue("evidence_integrity", item_id, reference))
            elif reference in DOCUMENT_CONTRACTS and not _documentary_evidence(
                candidate, reference
            ):
                issues.append(Issue("documentary_evidence", item_id, reference))
            elif (
                reference == "scripts/sweep_chunk_size.py"
                and _sweep_digest(candidate) != SWEEP_DIGEST
            ):
                issues.append(Issue("evidence_integrity", item_id, reference))
        entries.append(StatusEntry(item_id, status, evidence, follow_up, follow_up_detail))

    for item_id, count in counts.items():
        if count == 0:
            issues.append(Issue("missing_id", item_id, "required row is absent"))
        elif count > 1:
            issues.append(Issue("duplicate_id", item_id, f"found {count} rows"))

    issues.extend(_evidence_path_issues(root))

    return StatusReport(
        not issues,
        tuple(entries),
        tuple(sorted(resolved_paths)),
        tuple(issues),
    )


def _validate_pytest_receipt(
    receipt: Path,
    *,
    expected_count: int,
    expected_nodes: frozenset[str] | None = None,
) -> Issue | None:
    try:
        root = ET.parse(receipt).getroot()
        suites = root.findall(".//testsuite")
        testcases = root.findall(".//testcase")
        tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
        failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
        errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
        skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    except (ET.ParseError, OSError, ValueError):
        return Issue("evidence_execution", "DOCUMENT", "pytest receipt is missing or malformed")

    # An import or collection error is not a failing assertion, and saying "failed" sends
    # the reader looking at the product for a defect that is really a broken module.
    if errors:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest could not collect or set up {errors} canonical nodes",
        )
    if failures:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest failed {failures} canonical nodes",
        )
    if skipped:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest skipped {skipped} canonical nodes",
        )
    if tests != expected_count:
        return Issue(
            "evidence_execution",
            "DOCUMENT",
            f"pytest executed {tests} of {expected_count} canonical nodes",
        )
    if expected_nodes is not None:
        executed_nodes = frozenset(
            f"{case.attrib['file']}::{case.attrib['name']}"
            for case in testcases
            if "file" in case.attrib and "name" in case.attrib
        )
        if executed_nodes != expected_nodes:
            missing = sorted(expected_nodes - executed_nodes)
            unexpected = sorted(executed_nodes - expected_nodes)
            return Issue(
                "evidence_execution",
                "DOCUMENT",
                f"pytest node mismatch: missing={missing}; unexpected={unexpected}",
            )
    return None


def _execute_test_evidence(root: Path) -> tuple[Issue | None, int]:
    node_ids = sorted(TEST_EVIDENCE_DIGESTS)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTEST_ADDOPTS", None)
    environment.pop("PYTEST_PLUGINS", None)
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    # A per-run secret handed to the child over a pipe, never over argv and never through
    # the filesystem. The child's report has to be signed with it to count.
    secret = binascii.hexlify(os.urandom(32))
    read_fd, write_fd = os.pipe()
    os.write(write_fd, secret)
    os.close(write_fd)
    before = _tree_snapshot(root)
    with tempfile.TemporaryDirectory(prefix="ontologylab-evidence-") as temporary:
        temporary_path = Path(temporary)
        receipt = temporary_path / "pytest.xml"
        plan_file = temporary_path / "plan.json"
        ledger_file = temporary_path / "ledger.json"
        plan_file.write_text(
            json.dumps(
                {
                    "nodes": {
                        node_id: {
                            "path": node_id.split("::", 1)[0],
                            "name": node_id.split("::", 1)[1],
                            "digest": digest,
                        }
                        for node_id, digest in TEST_EVIDENCE_DIGESTS.items()
                    },
                    "modules": dict(EVIDENCE_MODULE_DIGESTS),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        controlled_config = temporary_path / "pytest.ini"
        controlled_config.write_text("[pytest]\naddopts =\n", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                # `-S` as well as `-I`: `.pth` files in site-packages execute before any
                # `-c` program, which is early enough to read the run secret off the
                # inherited descriptor and sign a forged pass. The child rebuilds the path
                # it needs from ONTOLOGYLAB_STATUS_SITEDIRS instead.
                "-S",
                "-c",
                EVIDENCE_EXECUTOR_PROGRAM,
                str(root),
                str(plan_file),
                str(ledger_file),
                str(read_fd),
                "-q",
                "-c",
                str(controlled_config),
                "--rootdir",
                str(root),
                "--noconftest",
                # An audit that writes into the tree it audits is not read-only, and the
                # gate normally runs as `--root .` against the real checkout.
                "-p",
                "no:cacheprovider",
                "-o",
                "addopts=",
                "-o",
                "junit_family=legacy",
                "--junitxml",
                str(receipt),
                *node_ids,
            ],
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            pass_fds=(read_fd,),
        )
        os.close(read_fd)
        ledger, ledger_issue, signed_returncode = _read_execution_ledger(
            ledger_file, secret, root
        )
        receipt_issue = _validate_pytest_receipt(
            receipt,
            expected_count=len(node_ids),
            expected_nodes=frozenset(node_ids),
        )
        refusals = _executor_refusals(result.stdout)
        writes = _tree_writes(root, before)
    # A refusal is the gate declining to accept the run at all — an ambiguous digest, an
    # undeclared module, a signature it will not call. Reporting only the failed-node
    # count would leave those looking like ordinary assertion failures.
    if refusals:
        return (
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"executor refused the run: {refusals}",
            ),
            len(ledger),
        )
    if writes:
        return (
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"the audited run wrote inside the audited tree: {writes[:20]}",
            ),
            len(ledger),
        )
    # Substitution outranks damage. "N nodes failed" describes a product that is broken; a
    # substitution finding says the run does not describe the product on disk at all, which
    # is the stronger statement and the one an operator needs first -- reporting the count
    # first buried substitution behind whatever damage the substitution happened to leave.
    # A short ledger, by contrast, is the *expected* consequence of nodes failing, so it
    # stays behind the count that explains it.
    if ledger_issue is not None and ledger_issue.detail.startswith(
        ("product code the bodies called", "product changed between")
    ):
        return ledger_issue, len(ledger)
    if receipt_issue is not None:
        return receipt_issue, len(ledger)
    if ledger_issue is not None:
        return ledger_issue, len(ledger)
    # The signed exit code, not the process's: `os._exit(0)` can forge the latter.
    if signed_returncode != 0:
        output = "\n".join(
            part.strip() for part in (result.stdout, result.stderr) if part.strip()
        )
        return (
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"pytest exit {signed_returncode}: {output[-4000:]}",
            ),
            len(ledger),
        )
    return None, len(ledger)


def _tree_writes(root: Path, before: dict[str, int]) -> list[str]:
    """Paths the audited run created or changed inside the tree it was auditing.

    `-p no:cacheprovider` stops the one writer that existed. This checks the property
    instead of trusting the flag, because the gate normally runs against the real checkout,
    and `--noconftest` means the suite's own "never touch the developer's settings" guard is
    not loaded to catch a future canonical node that writes where it should not.
    """
    return sorted(
        path
        for path, stamp in _tree_snapshot(root).items()
        if before.get(path) != stamp
    )


def _tree_snapshot(root: Path) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for path in root.rglob("*"):
        if any(part in {".git", ".venv", "__pycache__"} for part in path.parts):
            continue
        try:
            snapshot[str(path)] = path.stat().st_mtime_ns if path.is_file() else 0
        except OSError:
            continue
    return snapshot


def _executor_refusals(output: str) -> list[str]:
    """Pull the child's own structural refusals out of its report."""
    markers = (
        "definitions carry the audited digest",
        "no declared module digest",
        "module digest",
        "audited definition is decorated",
        "audited definition is async",
        "audited signature is not plain fixtures",
    )
    return sorted(
        {
            line.strip().removeprefix("E   ").strip()
            for line in output.splitlines()
            if line.lstrip().startswith("E ")
            and any(marker in line for marker in markers)
        }
    )


def _read_execution_ledger(
    ledger_file: Path, secret: bytes, root: Path
) -> tuple[dict[str, str], Issue | None, int]:
    """Read what the child compiled, ran, and loaded, and hold it to the digests.

    The report must carry an HMAC over its own payload keyed by the run secret. The child
    drains that secret from a pipe and closes it before any repository code runs, so a
    later writer -- an `atexit` hook, a product import, anything that reaches the paths on
    the child's argv -- can rewrite these files but cannot sign them.
    """
    malformed = Issue(
        "evidence_execution", "DOCUMENT", "execution ledger is missing or malformed"
    )
    try:
        envelope = json.loads(ledger_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, malformed, _UNSIGNED
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"payload", "signature"}
        or not isinstance(envelope["payload"], str)
        or not isinstance(envelope["signature"], str)
    ):
        return (
            {},
            Issue(
                "evidence_execution",
                "DOCUMENT",
                "execution report is not signed by this run",
            ),
            _UNSIGNED,
        )
    expected = hmac.new(
        secret, envelope["payload"].encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, envelope["signature"]):
        return (
            {},
            Issue(
                "evidence_execution",
                "DOCUMENT",
                "execution report is not signed by this run",
            ),
            _UNSIGNED,
        )
    try:
        ledger = json.loads(envelope["payload"])
    except json.JSONDecodeError:
        return {}, malformed, _UNSIGNED
    if not isinstance(ledger, dict) or set(ledger) != {
        "executed",
        "modules",
        "unaudited",
        "returncode",
        "product",
        "substituted",
    }:
        return {}, malformed, _UNSIGNED
    executed, modules, unaudited = (
        ledger["executed"],
        ledger["modules"],
        ledger["unaudited"],
    )
    product, substituted = ledger["product"], ledger["substituted"]
    if (
        not isinstance(ledger["returncode"], int)
        or not isinstance(product, dict)
        or not isinstance(substituted, list)
    ):
        return {}, malformed, _UNSIGNED
    signed_returncode = ledger["returncode"]
    if (
        not isinstance(executed, dict)
        or not isinstance(modules, dict)
        or not isinstance(unaudited, list)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for mapping in (executed, modules)
            for key, value in mapping.items()
        )
    ):
        return {}, malformed, _UNSIGNED

    if substituted:
        return (
            executed,
            Issue(
                "evidence_execution",
                "DOCUMENT",
                "product code the bodies called is not what its own source compiles to: "
                f"{sorted(substituted)[:20]}",
            ),
            signed_returncode,
        )
    if executed != dict(TEST_EVIDENCE_DIGESTS):
        missing = sorted(set(TEST_EVIDENCE_DIGESTS) - set(executed))
        unexpected = sorted(set(executed) - set(TEST_EVIDENCE_DIGESTS))
        divergent = sorted(
            node_id
            for node_id, digest in executed.items()
            if TEST_EVIDENCE_DIGESTS.get(node_id) not in (None, digest)
        )
        return (
            executed,
            Issue(
                "evidence_execution",
                "DOCUMENT",
                "executed source mismatch: "
                f"missing={missing}; unexpected={unexpected}; divergent={divergent}",
            ),
            signed_returncode,
        )
    if modules != dict(EVIDENCE_MODULE_DIGESTS):
        divergent = sorted(set(EVIDENCE_MODULE_DIGESTS).symmetric_difference(modules))
        return (
            executed,
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"evidence module digests were not all verified in-run: {divergent}",
            ),
            signed_returncode,
        )
    if unaudited:
        return (
            executed,
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"unaudited repository modules on the evidence path: {sorted(unaudited)}",
            ),
            signed_returncode,
        )
    if not product:
        return (
            executed,
            Issue(
                "evidence_execution",
                "DOCUMENT",
                "no product module identity was recorded for this run",
            ),
            signed_returncode,
        )
    # Only the product modules the run actually loaded: the parent is confirming that what
    # the bodies ran against is still what is on disk, not taking inventory of the tree.
    on_disk = _product_digests(root)
    if any(product.get(relative) != on_disk.get(relative) for relative in product):
        divergent = sorted(
            relative
            for relative in product
            if product.get(relative) != on_disk.get(relative)
        )
        return (
            executed,
            Issue(
                "evidence_execution",
                "DOCUMENT",
                f"product changed between the audited run and this check: {divergent[:20]}",
            ),
            signed_returncode,
        )
    return executed, None, signed_returncode


def _product_digests(root: Path) -> dict[str, str]:
    """Hash the product files the audited run reported loading.

    Identity reporting, not a content pin: there is no expected value here, only the
    requirement that the product the bodies ran against is the product still on disk.
    """
    product = root / "ontologylab"
    digests: dict[str, str] = {}
    for path in sorted(product.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest = _module_digest(path)
        if digest is not None:
            digests[path.relative_to(root).as_posix()] = digest
    return digests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument(
        "--document",
        type=Path,
        default=Path("docs/PRODUCT_SPEC.md"),
        help="status document, absolute or relative to --root",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    report = check_status(args.document, args.root)
    executed = 0
    if report.ok:
        execution_issue, executed = _execute_test_evidence(args.root.resolve())
        if execution_issue is not None:
            report = StatusReport(
                False,
                report.entries,
                report.resolved_paths,
                report.issues + (execution_issue,),
            )
    if report.ok:
        print(
            f"EVIDENCE: {executed} canonical pytest nodes passed",
            file=sys.stderr,
        )
    if args.json:
        print(json.dumps(report.payload(), ensure_ascii=False, sort_keys=True))
    else:
        verdict = "PASS" if report.ok else "FAIL"
        print(f"{verdict}: {len(report.entries)} statuses, {len(report.resolved_paths)} paths")
        for issue in report.issues:
            print(f"{issue.code}: {issue.item_id}: {issue.detail}")
    return 0 if report.ok else 1


def _reexec_isolated() -> None:
    """Re-run this checker with no site processing before it does anything else.

    DECLARED BOUNDARY (docs/PRODUCT_SPEC.md §7.1, case 2): this runs *after* `site`, so
    startup code and stdlib shadowing in the first parent are outside what this can close.
    The operational answer stated in the spec is to invoke the checker with `-P`, or to move
    it out of `scripts/`; neither is achievable from inside this function.

    Two rounds of this. First `-I`, because `site` imported `sitecustomize` from an
    inherited `PYTHONPATH` straight into the process that *prints the receipt*, where it
    replaced `subprocess.run` and handed every parent gate data it had written itself.

    `-I` was not enough: it implies `-E -s -P` but **not** `-S`, so `.pth` files in the
    invoking interpreter's site-packages still executed, in both this process and the
    child, before either had run a line of checker code. A `.pth` that read the run secret
    off the inherited descriptor could sign a complete thirteen-node pass with nothing
    executed. The answer is not to inspect `.pth` files but to stop running other people's
    startup code at all: `-S` disables path configuration wholesale, and the site directory
    the child needs is resolved here, while `site` still works, and handed over explicitly.
    """
    if sys.flags.isolated and sys.flags.no_site and sys.flags.safe_path:
        return
    if os.environ.get("ONTOLOGYLAB_STATUS_REEXEC") == "1":
        raise SystemExit("checker re-exec did not take effect; refusing to continue")
    import site

    # The audited root, as this invocation spells it, so it can never be mistaken for a
    # library directory below.
    args_root = Path.cwd()
    for index, argument in enumerate(sys.argv[1:]):
        if argument == "--root" and index + 2 <= len(sys.argv[1:]):
            args_root = Path(sys.argv[index + 2])
            break
        if argument.startswith("--root="):
            args_root = Path(argument.split("=", 1)[1])
            break
    environment = os.environ.copy()
    environment["ONTOLOGYLAB_STATUS_REEXEC"] = "1"
    # Captured before `-S` hides the virtual environment: under `-S` both `sys.prefix` and
    # `site.getsitepackages()` collapse to the base interpreter.
    # Only real library directories. `sys.path` also carries "" (the working directory) and,
    # under pytest, the repository root itself; either would exempt the whole tree from the
    # reach audit. Site directories are what the child needs, so that is what it gets.
    audited = Path(getattr(args_root, "resolve", lambda: args_root)()).resolve()
    environment["ONTOLOGYLAB_STATUS_SITEDIRS"] = os.pathsep.join(
        dict.fromkeys(
            entry
            for entry in site.getsitepackages()
            if entry
            and Path(entry).is_absolute()
            and Path(entry).is_dir()
            # Belt, and unreachable while the source above is `site.getsitepackages()`,
            # which never yields the audited tree. Kept because the previous iteration fed
            # `sys.path` in here, which does carry "" and the repository root, and that
            # exempted the whole tree from the reach audit. No test fails without this line.
            and Path(entry).resolve() != audited
        )
    )
    # `execve`, not `execv`: the replacement environment is passed to the call rather than
    # written into this process first, so a re-exec that does not happen leaves no trace in
    # the caller. `exec*`, not `subprocess`, because injected code already inside this
    # process can filter `subprocess.run` -- and did, in the shape this closes. Replacing the
    # process image leaves nothing of the compromised interpreter behind to intercept.
    os.execve(
        sys.executable,
        # `-P` as well: without it `sys.path[0]` is `scripts/`, so a `scripts/pytest.py`
        # would be imported in preference to the real package, pre-drain, from a directory
        # the audit never looks at.
        [sys.executable, "-I", "-S", "-P", str(Path(__file__).resolve()), *sys.argv[1:]],
        environment,
    )


if __name__ == "__main__":
    _reexec_isolated()
    raise SystemExit(main())
