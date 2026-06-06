"""Offline test runner (pytest is not installed in this build sandbox).

Imports each new TIER-1 test module, instantiates every Test* class, runs every test_*
method, and reports pass/fail. The suites are intentionally fixture-free so they run
identically here and under `pytest` in the repo.
"""
import importlib
import traceback

MODULES = [
    "tests.test_dosing",
    "tests.test_medication_safety",
    "tests.test_dose_log",
    "tests.test_eval_metrics",
    "tests.test_hybrid_retrieval",
]

total = passed = failed = 0
failures = []

for mod_name in MODULES:
    mod = importlib.import_module(mod_name)
    classes = [getattr(mod, n) for n in dir(mod)
               if n.startswith("Test") and isinstance(getattr(mod, n), type)]
    for cls in classes:
        inst = cls()
        methods = [m for m in dir(inst) if m.startswith("test_")]
        for m in methods:
            total += 1
            label = f"{mod_name}::{cls.__name__}::{m}"
            try:
                getattr(inst, m)()
                passed += 1
                print(f"PASS  {label}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                failures.append((label, e, traceback.format_exc()))
                print(f"FAIL  {label}  -> {e!r}")

print("\n" + "=" * 70)
print(f"  {passed}/{total} passed, {failed} failed")
print("=" * 70)
if failures:
    for label, e, tb in failures:
        print(f"\n--- {label} ---\n{tb}")
    raise SystemExit(1)
