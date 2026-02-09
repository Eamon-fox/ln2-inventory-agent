"""
Business logic operations for LN2 inventory
"""


def find_record_by_id(records, record_id):
    """
    Find a record by its ID

    Args:
        records: List of inventory records
        record_id: ID to search for

    Returns:
        tuple: (index, record) if found, (None, None) otherwise
    """
    for idx, rec in enumerate(records):
        if rec.get("id") == record_id:
            return idx, rec
    return None, None


def check_position_conflicts(records, box, positions):
    """
    Check if positions are already occupied

    Args:
        records: List of inventory records
        box: Box number to check
        positions: List of positions to check

    Returns:
        list: List of conflict dicts with keys: id, short_name, positions
    """
    conflicts = []
    for rec in records:
        if rec.get("box") != box:
            continue
        rec_positions = rec.get("positions", [])
        overlap = set(positions) & set(rec_positions)
        if overlap:
            conflicts.append({
                "id": rec.get("id"),
                "short_name": rec.get("short_name"),
                "positions": sorted(overlap)
            })
    return conflicts


def get_next_id(records):
    """
    Get the next available ID

    Args:
        records: List of inventory records

    Returns:
        int: Next available ID
    """
    if not records:
        return 1
    return max(rec.get("id", 0) for rec in records) + 1
