"""Performance probe for OverviewPanel grid rendering and staging pipeline.

Usage:
    1. Start the GUI normally:  python app_gui/main.py
    2. In a separate terminal, or add to main.py before app.exec():
         import perf_probe; perf_probe.install(window)
    3. Click "入库" several times, then click grid cells.
    4. Call perf_probe.report() to see the summary,
       or it auto-prints every 10 seconds.

Alternatively, run this file directly to auto-patch:
    python perf_probe.py
"""

import functools
import time
import threading

# ── Storage ──────────────────────────────────────────────────────────

_stats_lock = threading.Lock()
_stats = {}          # key → {"calls": int, "total_ms": float, "max_ms": float}
_call_log = []       # [(timestamp, func_name, duration_ms), ...]
_MAX_LOG = 2000


def _record(name, duration_ms):
    with _stats_lock:
        entry = _stats.setdefault(name, {"calls": 0, "total_ms": 0.0, "max_ms": 0.0})
        entry["calls"] += 1
        entry["total_ms"] += duration_ms
        if duration_ms > entry["max_ms"]:
            entry["max_ms"] = duration_ms
        if len(_call_log) < _MAX_LOG:
            _call_log.append((time.time(), name, duration_ms))


# ── Wrapping helpers ─────────────────────────────────────────────────

def _wrap_method(owner_module, method_name, probe_name=None):
    """Wrap a module-level function (used as a method via monkeypatch)."""
    original = getattr(owner_module, method_name)
    label = probe_name or f"{owner_module.__name__}.{method_name}"

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = original(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000
        _record(label, dt)
        return result

    setattr(owner_module, method_name, wrapper)
    return original


def _wrap_instance_method(obj, method_name, probe_name=None):
    """Wrap a bound method on a specific object instance."""
    original = getattr(obj, method_name)
    label = probe_name or f"{obj.__class__.__name__}.{method_name}"

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = original(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000
        _record(label, dt)
        return result

    setattr(obj, method_name, wrapper)
    return original


def _wrap_class_method(cls, method_name, probe_name=None):
    """Wrap a method on a class (for functions bound as class attributes)."""
    original = getattr(cls, method_name)
    label = probe_name or f"{cls.__name__}.{method_name}"

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = original(*args, **kwargs)
        dt = (time.perf_counter() - t0) * 1000
        _record(label, dt)
        return result

    setattr(cls, method_name, wrapper)
    return original


# ── Count-only wrapper (for very hot functions) ──────────────────────

_paint_cell_count = 0
_paint_cell_total_ms = 0.0


def _wrap_paint_cell(owner_module):
    """Special wrapper for _paint_cell that tracks per-cell cost."""
    original = getattr(owner_module, "_paint_cell")

    @functools.wraps(original)
    def wrapper(self_arg, button, box_num, position, record):
        global _paint_cell_count, _paint_cell_total_ms
        t0 = time.perf_counter()
        result = original(self_arg, button, box_num, position, record)
        dt = (time.perf_counter() - t0) * 1000
        _paint_cell_count += 1
        _paint_cell_total_ms += dt
        return result

    setattr(owner_module, "_paint_cell", wrapper)
    return original


# ── Install probes ───────────────────────────────────────────────────

_installed = False


def install(window=None):
    """Install performance probes on key rendering and staging paths.

    Call with the main window object, or with None to patch modules only.
    """
    global _installed
    if _installed:
        print("[perf_probe] Already installed.")
        return
    _installed = True

    from app_gui.ui import overview_panel_grid as _grid
    from app_gui.ui import overview_panel_refresh as _refresh
    from app_gui.ui import overview_panel_filters as _filters
    from app_gui.ui import overview_panel_zoom as _zoom
    from app_gui.ui.overview_panel import OverviewPanel as _OvCls

    # ── Class-bound methods (must patch the class, not the module) ────
    # These functions are bound as class attributes at import time, so
    # module-level wrapping has no effect on self.method() calls.

    # 0. Zoom probes
    _wrap_class_method(_OvCls, "_set_zoom", "set_zoom")
    _wrap_class_method(_OvCls, "_apply_zoom", "apply_zoom")

    # 1. _repaint_all_cells — the hot path without signature optimization
    _wrap_class_method(_OvCls, "_repaint_all_cells", "repaint_all_cells")

    # 2. _paint_cell — per-cell cost (class-bound)
    _wrap_class_method(_OvCls, "_paint_cell", "paint_cell")

    # 3. refresh — the full refresh path (has signature optimization)
    _wrap_class_method(_OvCls, "refresh", "refresh")

    # 4. _apply_filters_grid
    _wrap_class_method(_OvCls, "_apply_filters_grid", "apply_filters_grid")

    # 5. _build_cell_render_signature
    _wrap_method(_grid, "_build_cell_render_signature", "build_cell_render_signature")

    # 6. _on_plan_store_changed
    _wrap_method(_grid, "_on_plan_store_changed", "on_plan_store_changed")

    # 7. _set_plan_markers_from_items
    _wrap_method(_grid, "_set_plan_markers_from_items", "set_plan_markers")

    # ── Staging pipeline probes ──────────────────────────────────────

    # 8. preflight_plan — the suspected main bottleneck
    from app_gui import plan_executor as _executor
    _wrap_method(_executor, "preflight_plan", "preflight_plan")

    # 9. run_plan (preflight mode)
    _wrap_method(_executor, "run_plan", "run_plan")

    # 10. load_yaml — may be called multiple times per preflight
    from lib import yaml_ops as _yaml
    _wrap_method(_yaml, "load_yaml", "load_yaml")

    # 11. write_yaml — temp copy in preflight
    _wrap_method(_yaml, "write_yaml", "write_yaml")

    # 12. validate_stage_request — top-level staging gate
    from app_gui import plan_gate as _gate
    _wrap_method(_gate, "validate_stage_request", "validate_stage_request")
    _wrap_method(_gate, "validate_plan_batch", "validate_plan_batch")

    # 13. tool_add_entry — called per-item during preflight
    from lib import tool_api as _tapi
    _wrap_method(_tapi, "tool_add_entry", "tool_add_entry")

    # Instance-level patches if window is provided
    if window is not None:
        ops = getattr(window, "operations_panel", None)
        if ops is not None:
            from app_gui.ui import operations_panel_plan_toolbar as _toolbar
            _wrap_method(_toolbar, "_refresh_after_plan_items_changed", "refresh_plan_table")

            from app_gui.ui import operations_panel_plan_store as _pstore
            _wrap_method(_pstore, "add_plan_items", "add_plan_items")

    print("[perf_probe] Probes installed. Use perf_probe.report() to see results.")
    print("[perf_probe] Or wait — auto-report prints every 10 seconds if there's new data.")

    # Start background reporter
    _start_auto_report()


# ── Report ───────────────────────────────────────────────────────────

_last_report_calls = 0


def report():
    """Print a formatted performance summary."""
    global _last_report_calls

    with _stats_lock:
        snapshot = {k: dict(v) for k, v in _stats.items()}

    total_calls = sum(v["calls"] for v in snapshot.values())
    if total_calls == 0:
        print("[perf_probe] No data yet. Perform some GUI actions first.")
        return

    print()
    print("=" * 78)
    print("  PERFORMANCE PROBE REPORT")
    print("=" * 78)
    print(f"  {'Function':<35} {'Calls':>7} {'Total ms':>10} {'Avg ms':>9} {'Max ms':>9}")
    print("-" * 78)

    for name in sorted(snapshot, key=lambda k: snapshot[k]["total_ms"], reverse=True):
        s = snapshot[name]
        avg = s["total_ms"] / s["calls"] if s["calls"] else 0
        print(f"  {name:<35} {s['calls']:>7} {s['total_ms']:>10.1f} {avg:>9.2f} {s['max_ms']:>9.2f}")

    # Legacy paint cell stats (if old-style wrapper was used)
    if _paint_cell_count > 0:
        avg_pc = _paint_cell_total_ms / _paint_cell_count
        print("-" * 78)
        print(f"  {'_paint_cell (per-cell)':<35} {_paint_cell_count:>7} {_paint_cell_total_ms:>10.1f} {avg_pc:>9.3f}")

    # Derived metrics
    print()
    print("  DERIVED METRICS:")

    # Staging pipeline breakdown
    stage_req = snapshot.get("validate_stage_request", {})
    preflight = snapshot.get("preflight_plan", {})
    load_y = snapshot.get("load_yaml", {})
    write_y = snapshot.get("write_yaml", {})
    add_entry = snapshot.get("tool_add_entry", {})
    add_items = snapshot.get("add_plan_items", {})

    if stage_req.get("calls", 0) > 0:
        print()
        print("  STAGING PIPELINE (per '存入' click):")
        avg_stage = stage_req["total_ms"] / stage_req["calls"]
        print(f"  - validate_stage_request avg:     {avg_stage:.1f} ms")

    if preflight.get("calls", 0) > 0:
        avg_pf = preflight["total_ms"] / preflight["calls"]
        print(f"  - preflight_plan avg:             {avg_pf:.1f} ms")

    if load_y.get("calls", 0) > 0 and stage_req.get("calls", 0) > 0:
        loads_per_stage = load_y["calls"] / stage_req["calls"]
        avg_load = load_y["total_ms"] / load_y["calls"]
        print(f"  - load_yaml calls per staging:    {loads_per_stage:.1f}x  (avg {avg_load:.1f} ms each)")
        print(f"  - load_yaml total:                {load_y['total_ms']:.1f} ms")

    if write_y.get("calls", 0) > 0:
        print(f"  - write_yaml total:               {write_y['total_ms']:.1f} ms ({write_y['calls']} calls)")

    if add_entry.get("calls", 0) > 0 and stage_req.get("calls", 0) > 0:
        adds_per_stage = add_entry["calls"] / stage_req["calls"]
        avg_add = add_entry["total_ms"] / add_entry["calls"]
        print(f"  - tool_add_entry per staging:     {adds_per_stage:.1f}x  (avg {avg_add:.1f} ms each)")

    # Grid rendering
    repaint = snapshot.get("repaint_all_cells", {})
    plan_table = snapshot.get("refresh_plan_table", {})

    paint = snapshot.get("paint_cell", {})
    if repaint.get("calls", 0) > 0:
        pc_count = paint.get("calls", _paint_cell_count) or 0
        cells_per_repaint = pc_count / repaint["calls"] if repaint["calls"] else 0
        print()
        print("  GRID RENDERING:")
        print(f"  - Cells per repaint_all_cells:    {cells_per_repaint:.0f}")
        print(f"  - Avg repaint_all_cells cost:     {repaint['total_ms']/repaint['calls']:.1f} ms")

    zoom_calls = snapshot.get("set_zoom", {})
    apply_calls = snapshot.get("apply_zoom", {})
    if zoom_calls.get("calls", 0) > 0:
        print()
        print("  ZOOM:")
        print(f"  - set_zoom calls:                 {zoom_calls['calls']}")
        print(f"  - apply_zoom calls:               {apply_calls.get('calls', 0)}")
        if repaint.get("calls", 0) > 0:
            ratio = repaint["calls"] / zoom_calls["calls"]
            print(f"  - repaints per zoom:              {ratio:.2f}  (ideal ≤1.0)")

    if plan_table.get("calls", 0) > 0 and add_items.get("calls", 0) > 0:
        ratio = plan_table["calls"] / add_items["calls"]
        print(f"  - refresh_plan_table / add_items:  {ratio:.1f}x  (should be 1.0, >1 = double-call)")

    # Show timeline of recent slow operations (>50ms)
    with _stats_lock:
        recent = list(_call_log)
    slow = [(ts, name, dt) for ts, name, dt in recent if dt > 50]
    if slow:
        print()
        print("  SLOW OPERATIONS (>50ms):")
        for ts, name, dt in slow[-15:]:
            t_str = time.strftime("%H:%M:%S", time.localtime(ts))
            print(f"    {t_str}  {name:<35} {dt:.1f} ms")

    print("=" * 78)
    print()

    _last_report_calls = total_calls


def reset():
    """Clear all collected data."""
    global _paint_cell_count, _paint_cell_total_ms, _last_report_calls
    with _stats_lock:
        _stats.clear()
        _call_log.clear()
    _paint_cell_count = 0
    _paint_cell_total_ms = 0.0
    _last_report_calls = 0
    print("[perf_probe] Stats reset.")


# ── Auto-reporter ────────────────────────────────────────────────────

_auto_report_timer = None


def _auto_report_tick():
    global _last_report_calls
    with _stats_lock:
        total_calls = sum(v["calls"] for v in _stats.values())
    if total_calls > _last_report_calls:
        report()
    # Reschedule
    _start_auto_report()


def _start_auto_report():
    global _auto_report_timer
    _auto_report_timer = threading.Timer(10.0, _auto_report_tick)
    _auto_report_timer.daemon = True
    _auto_report_timer.start()


# ── Standalone entry point ───────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os

    # Add project root to path
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    print("[perf_probe] Starting GUI with performance probes...")
    print("[perf_probe] Instructions:")
    print("  1. Click '存入' (add) several times to stage plan items")
    print("  2. Watch terminal for auto-reports every 10 seconds")
    print("  3. Focus on STAGING PIPELINE section in the report")
    print()

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Import and create main window
    from app_gui.main import MainWindow
    window = MainWindow()

    # Install probes
    install(window)

    window.show()
    sys.exit(app.exec())
