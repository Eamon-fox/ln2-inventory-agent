#!/usr/bin/env python3
"""
Generate an HTML visualization of the LN2 tank inventory.
Produces a 9x9 grid for each box showing occupied/empty positions.
"""
import argparse
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from lib.yaml_ops import load_yaml
from lib.config import YAML_PATH, BOX_RANGE

HTML_OUTPUT = os.path.join(os.path.dirname(YAML_PATH), "ln2_inventory.html")


def build_position_map(records):
    """Build a map of (box, position) -> record for active positions."""
    pos_map = {}
    for rec in records:
        box = rec.get("box")
        if box is None:
            continue
        for p in rec.get("positions") or []:
            pos_map[(int(box), int(p))] = rec
    return pos_map


def get_cell_color(parent):
    """Assign a color based on parent cell line."""
    colors = {
        "NCCIT": "#4a90d9",
        "K562": "#e67e22",
        "HeLa": "#27ae60",
        "HEK293T": "#8e44ad",
        "NCCIT Des-MCP-APEX2": "#2c3e50",
    }
    return colors.get(parent, "#7f8c8d")


def escape(s):
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")


def build_cell_line_counts(records):
    """Return per-cell-line occupied position counts (desc)."""
    counts = {}
    for rec in records:
        parent = rec.get("parent_cell_line") or "未知"
        counts[parent] = counts.get(parent, 0) + len(rec.get("positions") or [])
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def generate_html(data):
    records = data.get("inventory", [])
    pos_map = build_position_map(records)
    layout = data.get("meta", {}).get("box_layout", {})
    rows = int(layout.get("rows", 9))
    cols = int(layout.get("cols", 9))
    total = rows * cols
    box_count = BOX_RANGE[1] - BOX_RANGE[0] + 1
    total_slots = total * box_count
    total_occupied = len(pos_map)
    total_empty = total_slots - total_occupied
    total_pct = (total_occupied / total_slots * 100) if total_slots else 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    cell_line_counts = build_cell_line_counts(records)

    line_options = ['<option value="all">全部细胞系</option>']
    for parent, count in cell_line_counts:
        line_options.append(f'<option value="{escape(parent)}">{escape(parent)} ({count})</option>')

    box_options = ['<option value="all">全部盒子</option>']
    for box_num in range(BOX_RANGE[0], BOX_RANGE[1] + 1):
        box_options.append(f'<option value="{box_num}">盒子 {box_num}</option>')

    legend_html = '<div class="legend">'
    for parent, count in cell_line_counts:
        color = get_cell_color(parent)
        legend_html += (
            f'<button class="legend-chip" type="button" data-line="{escape(parent)}">'
            f'<span class="legend-dot" style="background:{color}"></span>'
            f'<span>{escape(parent)}</span>'
            f'<span class="legend-count">{count}</span>'
            '</button>'
        )
    legend_html += (
        '<button class="legend-chip" type="button" data-line="__empty__">'
        '<span class="legend-dot" style="background:#0f3460"></span>'
        '<span>空位</span>'
        f'<span class="legend-count">{total_empty}</span>'
        '</button>'
    )
    legend_html += '</div>'

    html_parts = []
    html_parts.append("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>液氮罐库存</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: "Segoe UI", "Noto Sans SC", sans-serif;
    background: radial-gradient(circle at top right, #28345b, #161c34 60%);
    color: #e7ebfb;
    padding: 18px;
}
.page { max-width: 1600px; margin: 0 auto; }
h1 { font-size: 1.8rem; letter-spacing: 0.02em; margin-bottom: 6px; }
.subtitle { color: #a5b0d8; font-size: 0.92rem; margin-bottom: 14px; }
.summary-grid {
    display: grid;
    grid-template-columns: repeat(5, minmax(120px, 1fr));
    gap: 10px;
    margin-bottom: 14px;
}
.summary-card {
    background: rgba(20, 28, 54, 0.75);
    border: 1px solid #2f3a63;
    border-radius: 10px;
    padding: 10px 12px;
}
.summary-label { color: #9aa8d2; font-size: 0.76rem; margin-bottom: 4px; display: block; }
.summary-value { font-size: 1.15rem; font-weight: 700; }
.toolbar {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr auto auto;
    gap: 10px;
    align-items: end;
    background: rgba(19, 27, 53, 0.8);
    border: 1px solid #2f3a63;
    border-radius: 12px;
    padding: 10px;
    margin-bottom: 12px;
}
.control { display: flex; flex-direction: column; gap: 6px; }
.control label { font-size: 0.75rem; color: #9aa8d2; }
.control input,
.control select {
    height: 36px;
    border-radius: 8px;
    border: 1px solid #3a4673;
    background: #121936;
    color: #e7ebfb;
    padding: 0 10px;
}
.control input::placeholder { color: #6f7ca9; }
.toggle {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.82rem;
    color: #c8d2f6;
    white-space: nowrap;
    margin-bottom: 9px;
}
.toolbar button {
    height: 36px;
    border-radius: 8px;
    border: 1px solid #4b5c98;
    background: #223369;
    color: #eef2ff;
    padding: 0 12px;
    cursor: pointer;
}
.toolbar button:hover { background: #2a3e7e; }
.match-summary {
    color: #9aa8d2;
    font-size: 0.82rem;
    margin-bottom: 12px;
}
.legend {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 14px;
}
.legend-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: 1px solid #394770;
    background: rgba(13, 21, 45, 0.8);
    color: #d7e0ff;
    border-radius: 999px;
    font-size: 0.76rem;
    padding: 5px 10px;
    cursor: pointer;
}
.legend-chip.active { border-color: #90a9ff; background: rgba(46, 72, 146, 0.6); }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; }
.legend-count { color: #95a3d1; }
.main-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 320px;
    gap: 14px;
    align-items: start;
}
.boxes {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(430px, 1fr));
    gap: 12px;
}
.box-container {
    background: rgba(19, 28, 56, 0.86);
    border: 1px solid #2f3a63;
    border-radius: 12px;
    padding: 10px;
}
.box-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}
.box-header { font-size: 0.95rem; font-weight: 700; }
.box-stats { color: #a6b2d9; font-size: 0.78rem; }
.box-stats-live { color: #7f8ebb; font-size: 0.72rem; margin-bottom: 8px; }
.progress { height: 6px; border-radius: 99px; background: #101833; overflow: hidden; margin-bottom: 8px; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #3f7ce8, #65c7ff); }
.grid { display: grid; gap: 3px; }
.cell {
    width: 42px;
    height: 42px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.64rem;
    position: relative;
    transition: transform 0.12s;
    line-height: 1.1;
    text-align: center;
    padding: 2px;
    overflow: visible;
}
.cell:focus-visible { outline: 2px solid #9bb7ff; outline-offset: 1px; }
.cell:hover,
.cell.active {
    transform: scale(1.12);
    z-index: 12;
    box-shadow: 0 0 0 1px rgba(255,255,255,0.25), 0 6px 16px rgba(0,0,0,0.45);
}
.cell.occupied { color: #fff; font-weight: 600; cursor: pointer; }
.cell.empty {
    background: #102449;
    color: #4f5d89;
    font-size: 0.58rem;
    border: 1px solid #233665;
}
.cell-label {
    display: block;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    pointer-events: none;
}
.tooltip {
    display: none;
    position: absolute;
    bottom: 108%;
    left: 50%;
    transform: translateX(-50%);
    background: #111827;
    color: #e6eaf9;
    padding: 9px 11px;
    border-radius: 7px;
    font-size: 11px;
    z-index: 50;
    border: 1px solid #3c4a73;
    line-height: 1.45;
    text-align: left;
    min-width: 200px;
    max-width: 290px;
    white-space: normal;
    pointer-events: none;
}
.cell:hover .tooltip,
.cell.active .tooltip { display: block; }
.detail-panel {
    position: sticky;
    top: 14px;
    background: rgba(19, 28, 56, 0.9);
    border: 1px solid #2f3a63;
    border-radius: 12px;
    padding: 12px;
}
.detail-panel h2 { font-size: 1rem; margin-bottom: 8px; }
.detail-hint { font-size: 0.78rem; color: #96a3ce; margin-bottom: 10px; }
.detail-list { display: grid; gap: 8px; }
.detail-item {
    background: rgba(11, 18, 37, 0.7);
    border: 1px solid #2f3a63;
    border-radius: 8px;
    padding: 8px;
}
.detail-label { display: block; color: #92a0cc; font-size: 0.72rem; margin-bottom: 2px; }
.detail-value { font-size: 0.84rem; word-break: break-word; }
.hidden { display: none !important; }

@media (max-width: 1280px) {
    .summary-grid { grid-template-columns: repeat(3, minmax(120px, 1fr)); }
    .toolbar { grid-template-columns: 2fr 1fr 1fr; }
}

@media (max-width: 980px) {
    .main-layout { grid-template-columns: 1fr; }
    .detail-panel { position: static; }
    .boxes { grid-template-columns: 1fr; }
    .toolbar { grid-template-columns: 1fr; }
    .summary-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
}
</style>
</head>
<body>
<div class="page">
""")

    html_parts.append('<h1>液氮罐库存</h1>')
    html_parts.append(f'<div class="subtitle">生成时间: {now} | 支持悬浮预览 + 点击固定详情 + 快速筛选</div>')

    html_parts.append(
        f'<div class="summary-grid">'
        f'<div class="summary-card"><span class="summary-label">总容量</span><span class="summary-value">{total_slots}</span></div>'
        f'<div class="summary-card"><span class="summary-label">已占用</span><span class="summary-value" id="visible-occupied">{total_occupied}</span></div>'
        f'<div class="summary-card"><span class="summary-label">空位</span><span class="summary-value" id="visible-empty">{total_empty}</span></div>'
        f'<div class="summary-card"><span class="summary-label">占用率</span><span class="summary-value">{total_pct:.1f}%</span></div>'
        f'<div class="summary-card"><span class="summary-label">记录条数</span><span class="summary-value">{len(records)}</span></div>'
        '</div>'
    )

    html_parts.append(
        '<div class="toolbar">'
        '<div class="control"><label for="search-input">搜索</label>'
        '<input id="search-input" type="text" placeholder="输入 ID / 细胞系 / 简称 / 质粒 / 备注"></div>'
        '<div class="control"><label for="box-filter">盒子</label>'
        f'<select id="box-filter">{"".join(box_options)}</select></div>'
        '<div class="control"><label for="line-filter">细胞系</label>'
        f'<select id="line-filter">{"".join(line_options)}</select></div>'
        '<label class="toggle"><input id="show-empty" type="checkbox" checked>显示空位</label>'
        '<button id="reset-filters" type="button">重置筛选</button>'
        '</div>'
    )

    html_parts.append(
        f'<div class="match-summary" id="match-summary">'
        f'当前显示 <strong id="visible-total">{total_slots}</strong> 格（占用 <strong>{total_occupied}</strong>，空位 <strong>{total_empty}</strong>）'
        '</div>'
    )

    html_parts.append(legend_html)

    html_parts.append('<div class="main-layout">')
    html_parts.append('<div class="boxes" id="boxes">')

    for box_num in range(BOX_RANGE[0], BOX_RANGE[1] + 1):
        occupied_count = sum(1 for p in range(1, total + 1) if (box_num, p) in pos_map)
        empty_count = total - occupied_count
        pct = occupied_count / total * 100 if total else 0

        html_parts.append(f'<div class="box-container" data-box="{box_num}">')
        html_parts.append(
            f'<div class="box-title-row">'
            f'<div class="box-header">盒子 {box_num}</div>'
            f'<div class="box-stats">{occupied_count}/{total} ({pct:.0f}%)</div>'
            '</div>'
        )
        html_parts.append(f'<div class="progress"><div class="progress-fill" style="width:{pct:.1f}%"></div></div>')
        html_parts.append(f'<div class="box-stats-live">筛选后: {occupied_count} 占用 / {empty_count} 空位</div>')
        html_parts.append(f'<div class="grid" style="grid-template-columns: repeat({cols}, 42px); grid-template-rows: repeat({rows}, 42px);">')

        for pos in range(1, total + 1):
            key = (box_num, pos)
            if key in pos_map:
                rec = pos_map[key]
                parent = rec.get("parent_cell_line", "")
                short = rec.get("short_name", "")
                color = get_cell_color(parent)
                frozen = rec.get("frozen_at", "")
                plasmid = rec.get("plasmid_name") or ""
                note = rec.get("note") or ""
                rec_id = rec.get("id", "")

                display = short[:6] if len(short) > 6 else short
                search_blob = " ".join([
                    str(rec_id),
                    str(box_num),
                    str(pos),
                    str(parent),
                    str(short),
                    str(frozen),
                    str(plasmid),
                    str(note),
                    f"盒{box_num}",
                    f"位{pos}",
                ]).lower()

                tooltip_lines = [
                    f"<b>#{rec_id}</b> | 盒{box_num} 位{pos}",
                    f"<b>{escape(parent)}</b> | {escape(short)}",
                    f"冻存: {escape(frozen)}",
                ]
                if plasmid:
                    tooltip_lines.append(f"质粒: {escape(plasmid[:80])}")
                if note:
                    tooltip_lines.append(f"备注: {escape(note[:80])}")
                tooltip_html = "<br>".join(tooltip_lines)

                html_parts.append(
                    f'<div class="cell occupied" style="background:{color}" tabindex="0" '
                    f'data-empty="0" data-box="{box_num}" data-position="{pos}" '
                    f'data-id="{escape(rec_id)}" data-parent="{escape(parent)}" '
                    f'data-short="{escape(short)}" data-frozen="{escape(frozen)}" '
                    f'data-plasmid="{escape(plasmid)}" data-note="{escape(note)}" '
                    f'data-search="{escape(search_blob)}">'
                    f'<span class="cell-label">{escape(display)}</span>'
                    f'<div class="tooltip">{tooltip_html}</div>'
                    '</div>'
                )
            else:
                empty_search = escape(f"空位 盒{box_num} 位{pos} box {box_num} position {pos}".lower())
                html_parts.append(
                    f'<div class="cell empty" data-empty="1" data-box="{box_num}" '
                    f'data-position="{pos}" data-search="{empty_search}">{pos}</div>'
                )

        html_parts.append('</div></div>')

    html_parts.append('</div>')

    html_parts.append(
        '<aside class="detail-panel" id="detail-panel">'
        '<h2>位置详情</h2>'
        '<p class="detail-hint" id="detail-hint">点击任意占用格可固定查看详情（Esc 或点击空白可关闭）</p>'
        '<div class="detail-list">'
        '<div class="detail-item"><span class="detail-label">ID</span><span class="detail-value" id="detail-id">-</span></div>'
        '<div class="detail-item"><span class="detail-label">位置</span><span class="detail-value" id="detail-location">-</span></div>'
        '<div class="detail-item"><span class="detail-label">细胞系</span><span class="detail-value" id="detail-parent">-</span></div>'
        '<div class="detail-item"><span class="detail-label">简称</span><span class="detail-value" id="detail-short">-</span></div>'
        '<div class="detail-item"><span class="detail-label">冻存日期</span><span class="detail-value" id="detail-frozen">-</span></div>'
        '<div class="detail-item"><span class="detail-label">质粒</span><span class="detail-value" id="detail-plasmid">-</span></div>'
        '<div class="detail-item"><span class="detail-label">备注</span><span class="detail-value" id="detail-note">-</span></div>'
        '</div>'
        '</aside>'
    )

    html_parts.append('</div>')

    html_parts.append("""
<script>
(function () {
    const searchInput = document.getElementById('search-input');
    const boxFilter = document.getElementById('box-filter');
    const lineFilter = document.getElementById('line-filter');
    const showEmpty = document.getElementById('show-empty');
    const resetFilters = document.getElementById('reset-filters');
    const matchSummary = document.getElementById('match-summary');
    const visibleTotalNode = document.getElementById('visible-total');
    const visibleOccupiedNode = document.getElementById('visible-occupied');
    const visibleEmptyNode = document.getElementById('visible-empty');

    const detailHint = document.getElementById('detail-hint');
    const detailId = document.getElementById('detail-id');
    const detailLocation = document.getElementById('detail-location');
    const detailParent = document.getElementById('detail-parent');
    const detailShort = document.getElementById('detail-short');
    const detailFrozen = document.getElementById('detail-frozen');
    const detailPlasmid = document.getElementById('detail-plasmid');
    const detailNote = document.getElementById('detail-note');

    const cells = Array.from(document.querySelectorAll('.cell'));
    const occupiedCells = Array.from(document.querySelectorAll('.cell.occupied'));
    const boxContainers = Array.from(document.querySelectorAll('.box-container'));
    const legendChips = Array.from(document.querySelectorAll('.legend-chip'));
    let activeCell = null;

    function norm(value) {
        return String(value || '').toLowerCase();
    }

    function resetDetail() {
        detailHint.style.display = 'block';
        detailId.textContent = '-';
        detailLocation.textContent = '-';
        detailParent.textContent = '-';
        detailShort.textContent = '-';
        detailFrozen.textContent = '-';
        detailPlasmid.textContent = '-';
        detailNote.textContent = '-';
    }

    function showDetail(cell) {
        const d = cell.dataset;
        detailHint.style.display = 'none';
        detailId.textContent = d.id || '-';
        detailLocation.textContent = `盒${d.box || '-'} 位${d.position || '-'}`;
        detailParent.textContent = d.parent || '-';
        detailShort.textContent = d.short || '-';
        detailFrozen.textContent = d.frozen || '-';
        detailPlasmid.textContent = d.plasmid || '-';
        detailNote.textContent = d.note || '-';
    }

    function clearActiveCell() {
        if (activeCell) {
            activeCell.classList.remove('active');
            activeCell = null;
        }
        resetDetail();
    }

    function activateCell(cell) {
        if (activeCell === cell) {
            clearActiveCell();
            return;
        }
        if (activeCell) {
            activeCell.classList.remove('active');
        }
        activeCell = cell;
        cell.classList.add('active');
        showDetail(cell);
    }

    function updateLegendState() {
        const selectedLine = lineFilter.value;
        legendChips.forEach((chip) => {
            const line = chip.dataset.line;
            if (line === '__empty__') {
                chip.classList.toggle('active', showEmpty.checked && selectedLine === 'all');
            } else {
                chip.classList.toggle('active', line === selectedLine);
            }
        });
    }

    function applyFilters() {
        const query = norm(searchInput.value.trim());
        const selectedBox = boxFilter.value;
        const selectedLine = lineFilter.value;
        const includeEmpty = showEmpty.checked;

        let visibleTotal = 0;
        let visibleOccupied = 0;
        let visibleEmpty = 0;

        cells.forEach((cell) => {
            const isEmpty = cell.dataset.empty === '1';
            const matchesBox = selectedBox === 'all' || cell.dataset.box === selectedBox;
            const matchesLine = selectedLine === 'all' || (!isEmpty && cell.dataset.parent === selectedLine);
            const matchesQuery = !query || norm(cell.dataset.search).includes(query);

            let shouldShow = matchesBox && matchesQuery;
            if (isEmpty) {
                shouldShow = shouldShow && includeEmpty;
            } else {
                shouldShow = shouldShow && matchesLine;
            }

            cell.classList.toggle('hidden', !shouldShow);

            if (shouldShow) {
                visibleTotal += 1;
                if (isEmpty) {
                    visibleEmpty += 1;
                } else {
                    visibleOccupied += 1;
                }
            }
        });

        boxContainers.forEach((box) => {
            const occ = box.querySelectorAll('.cell.occupied:not(.hidden)').length;
            const emp = box.querySelectorAll('.cell.empty:not(.hidden)').length;
            const boxVisible = occ + emp > 0;
            box.classList.toggle('hidden', !boxVisible);
            const liveNode = box.querySelector('.box-stats-live');
            if (liveNode) {
                liveNode.textContent = `筛选后: ${occ} 占用 / ${emp} 空位`;
            }
        });

        if (activeCell && activeCell.classList.contains('hidden')) {
            clearActiveCell();
        }

        visibleTotalNode.textContent = String(visibleTotal);
        visibleOccupiedNode.textContent = String(visibleOccupied);
        visibleEmptyNode.textContent = String(visibleEmpty);
        matchSummary.textContent = `当前显示 ${visibleTotal} 格（占用 ${visibleOccupied}，空位 ${visibleEmpty}）`;
        updateLegendState();
    }

    occupiedCells.forEach((cell) => {
        cell.addEventListener('click', (event) => {
            event.stopPropagation();
            activateCell(cell);
        });

        cell.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                activateCell(cell);
            }
            if (event.key === 'Escape') {
                clearActiveCell();
            }
        });
    });

    searchInput.addEventListener('input', applyFilters);
    boxFilter.addEventListener('change', applyFilters);
    lineFilter.addEventListener('change', applyFilters);
    showEmpty.addEventListener('change', applyFilters);

    resetFilters.addEventListener('click', () => {
        searchInput.value = '';
        boxFilter.value = 'all';
        lineFilter.value = 'all';
        showEmpty.checked = true;
        applyFilters();
    });

    legendChips.forEach((chip) => {
        chip.addEventListener('click', () => {
            const line = chip.dataset.line;
            if (line === '__empty__') {
                lineFilter.value = 'all';
                showEmpty.checked = true;
            } else {
                lineFilter.value = line;
            }
            applyFilters();
        });
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.cell.occupied') && !event.target.closest('#detail-panel')) {
            clearActiveCell();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            clearActiveCell();
        }
    });

    resetDetail();
    applyFilters();
})();
</script>
""")

    html_parts.append('</div>')
    html_parts.append('</body></html>')
    return "\n".join(html_parts)


def main():
    parser = argparse.ArgumentParser(description="Generate HTML visualization of LN2 inventory")
    parser.add_argument("--yaml", default=YAML_PATH)
    parser.add_argument("--output", "-o", default=HTML_OUTPUT)
    args = parser.parse_args()

    data = load_yaml(args.yaml)
    html = generate_html(data)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"generated {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
