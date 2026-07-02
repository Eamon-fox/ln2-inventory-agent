"""Best-effort mojibake (乱码) repair for YAML string values.

Legacy datasets occasionally carry UTF-8 text that was decoded through a
GBK/GB18030 codepage, producing garbled characters. These helpers detect the
most probable original text and repair it on load. The functions are pure and
carry no module-level state, so they are safe to call from any layer.
"""
from typing import Any

_COMMON_CJK_CHARS = set(
    "的一是在不了有和人这中大上个国"
    "我以要他时来用们到作地于出就分对"
    "成会可主发年动同工也能下过子说产"
    "种面而方后多定行学法所民得经"
)

_MOJIBAKE_SOURCE_ENCODINGS = ("gb18030", "gbk", "cp936")
_MOJIBAKE_MARKER_CHARS = set("闄瀹锛鍐鎴鍚绉鎿璁銆鏄鈥缁鐨娓鍙寮澶浣")


def _text_readability_score(text: str) -> float:
    if not text:
        return float("-inf")

    common = 0
    cjk_basic = 0
    cjk_rare = 0
    private_use = 0
    ascii_printable = 0
    chinese_punct = 0
    question_marks = 0

    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF:
            cjk_basic += 1
            if ch in _COMMON_CJK_CHARS:
                common += 1
        elif 0x3400 <= code <= 0x4DBF or 0x20000 <= code <= 0x2FA1F:
            cjk_rare += 1
        elif 0xE000 <= code <= 0xF8FF:
            private_use += 1
        elif 0x20 <= code <= 0x7E:
            ascii_printable += 1
        elif ch in "，。！？：；、“”‘’（）《》【】—…":
            chinese_punct += 1

        if ch == "?":
            question_marks += 1

    return (
        common * 3.0
        + cjk_basic * 0.45
        + ascii_printable * 0.12
        + chinese_punct * 0.35
        - cjk_rare * 1.9
        - private_use * 2.4
        - question_marks * 0.8
    )


def _marker_count(text: str) -> int:
    return sum(1 for ch in (text or "") if ch in _MOJIBAKE_MARKER_CHARS)


def _is_probable_mojibake_upgrade(source: str, candidate: str, source_score: float, candidate_score: float) -> bool:
    src_markers = _marker_count(source)
    if src_markers <= 0:
        return False

    cand_markers = _marker_count(candidate)
    # Candidate should remove at least one suspicious marker and not make readability much worse.
    if cand_markers >= src_markers:
        return False
    return candidate_score >= source_score - 0.6


def _repair_mojibake_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return text
    if len(text) < 4:
        return text
    if all(ord(ch) < 128 for ch in text):
        return text

    best = text
    best_score = _text_readability_score(text)

    for _ in range(2):
        improved = False
        for enc in _MOJIBAKE_SOURCE_ENCODINGS:
            try:
                raw = best.encode(enc)
                candidate = raw.decode("utf-8")
            except UnicodeError:
                continue
            if not candidate or candidate == best:
                continue

            candidate_score = _text_readability_score(candidate)
            # Require a small margin to avoid rewriting already-good strings.
            # For true UTF8->GBK mojibake, candidate existence is already a strong signal.
            if (
                candidate_score > best_score + 0.35
                or _is_probable_mojibake_upgrade(best, candidate, best_score, candidate_score)
            ):
                best = candidate
                best_score = candidate_score
                improved = True

        if not improved:
            break

    return best


def _repair_mojibake_values(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _repair_mojibake_values(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_repair_mojibake_values(value) for value in node]
    if isinstance(node, str):
        return _repair_mojibake_text(node)
    return node
