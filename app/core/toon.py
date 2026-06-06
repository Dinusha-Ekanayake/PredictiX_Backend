import re
from typing import Any, Dict, List, Union

def to_toon(val: Any, indent: int = 0) -> str:
    """
    Serializes a Python object into Token-Oriented Object Notation (TOON) string.
    """
    spacing = " " * indent
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        # We need to quote if it contains syntax characters or matches keywords
        if any(c in val for c in [",", "\n", ":", '"', "'", "[", "]", "{", "}"]) or val.strip() != val or val in ("true", "false", "null"):
            escaped = val.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
            return f'"{escaped}"'
        return val
    
    if isinstance(val, list):
        if not val:
            return f"{spacing}[]"
        # Check if list of uniform dicts for tabular encoding
        if all(isinstance(x, dict) for x in val) and len(val) > 0:
            keys = list(val[0].keys())
            if all(set(x.keys()) == set(keys) for x in val):
                header_keys = ",".join(keys)
                lines = [f"{spacing}[{len(val)}]{{{header_keys}}}:"]
                for item in val:
                    row_vals = []
                    for k in keys:
                        v = item[k]
                        row_vals.append(to_toon(v).replace("\n", " "))
                    lines.append(f"{spacing}  " + ",".join(row_vals))
                return "\n".join(lines)
        
        lines = []
        for x in val:
            if isinstance(x, (dict, list)):
                lines.append(f"{spacing}-")
                lines.append(to_toon(x, indent + 2))
            else:
                lines.append(f"{spacing}- {to_toon(x)}")
        return "\n".join(lines)

    if isinstance(val, dict):
        if not val:
            return f"{spacing}{{}}"
        lines = []
        for k, v in val.items():
            if isinstance(v, (dict, list)) and v:
                if isinstance(v, list) and all(isinstance(x, dict) for x in v) and len(v) > 0:
                    keys = list(v[0].keys())
                    if all(set(x.keys()) == set(keys) for x in v):
                        header_keys = ",".join(keys)
                        lines.append(f"{spacing}{k}[{len(v)}]{{{header_keys}}}:")
                        for item in v:
                            row_vals = []
                            for rk in keys:
                                row_vals.append(to_toon(item[rk]).replace("\n", " "))
                            lines.append(f"{spacing}  " + ",".join(row_vals))
                        continue
                lines.append(f"{spacing}{k}:")
                lines.append(to_toon(v, indent + 2))
            else:
                lines.append(f"{spacing}{k}: {to_toon(v)}")
        return "\n".join(lines)
    return str(val)


def parse_val(s: str) -> Any:
    s = s.strip()
    if not s:
        return None
    if s == "null":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "[]":
        return []
    if s == "{}":
        return {}
    if s.startswith('"') and s.endswith('"'):
        inner = s[1:-1]
        res = ""
        i = 0
        while i < len(inner):
            if inner[i] == '\\' and i + 1 < len(inner):
                esc = inner[i+1]
                if esc == 'n':
                    res += '\n'
                else:
                    res += esc
                i += 2
            else:
                res += inner[i]
                i += 1
        return res
    # Try parsing as float or int
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return s


def split_csv_line(line: str) -> List[str]:
    result = []
    current = []
    in_quotes = False
    escaped = False
    i = 0
    while i < len(line):
        c = line[i]
        if escaped:
            current.append(c)
            escaped = False
        elif c == '\\':
            current.append(c)
            escaped = True
        elif c == '"':
            in_quotes = not in_quotes
            current.append(c)
        elif c == ',' and not in_quotes:
            result.append("".join(current))
            current = []
        else:
            current.append(c)
        i += 1
    result.append("".join(current))
    return [parse_val(x) for x in result]


def parse_toon(text: str) -> Any:
    """
    Parses a Token-Oriented Object Notation (TOON) string back into Python objects.
    """
    lines = []
    for line in text.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(' '))
        lines.append((indent, line.strip()))
    
    if not lines:
        return None
    
    def parse_block(start_idx: int, end_idx: int) -> Any:
        if start_idx > end_idx:
            return None
        
        base_indent, first_line = lines[start_idx]
        
        # Check if list of items
        if first_line.startswith("-"):
            items = []
            curr_idx = start_idx
            while curr_idx <= end_idx:
                indent, line = lines[curr_idx]
                if indent == base_indent and line.startswith("-"):
                    item_start = curr_idx
                    item_end = curr_idx
                    next_idx = curr_idx + 1
                    while next_idx <= end_idx:
                        if lines[next_idx][0] > base_indent:
                            item_end = next_idx
                            next_idx += 1
                        else:
                            break
                    
                    val_str = line[1:].strip()
                    if val_str:
                        items.append(parse_val(val_str))
                    else:
                        items.append(parse_block(item_start + 1, item_end))
                    curr_idx = next_idx
                else:
                    curr_idx += 1
            return items
        
        # Check if root/block itself is tabular
        tab_match = re.match(r'^([^\[]*)\[\d+\]\{([^\}]+)\}:$', first_line)
        if tab_match:
            name = tab_match.group(1).strip()
            fields = [f.strip() for f in tab_match.group(2).split(",")]
            rows = []
            for i in range(start_idx + 1, end_idx + 1):
                indent, line = lines[i]
                row_vals = split_csv_line(line)
                obj_item = {}
                for idx, f in enumerate(fields):
                    val = row_vals[idx] if idx < len(row_vals) else None
                    obj_item[f] = val
                rows.append(obj_item)
            return rows if not name else {name: rows}
        
        # Parse dict key-values
        obj = {}
        curr_idx = start_idx
        while curr_idx <= end_idx:
            indent, line = lines[curr_idx]
            if indent == base_indent:
                if ":" in line:
                    key_part, val_part = line.split(":", 1)
                    key = key_part.strip()
                    val_str = val_part.strip()
                    
                    item_end = curr_idx
                    next_idx = curr_idx + 1
                    while next_idx <= end_idx:
                        if lines[next_idx][0] > base_indent:
                            item_end = next_idx
                            next_idx += 1
                        else:
                            break
                    
                    # Check if the key indicates a tabular nested array
                    tab_key_match = re.match(r'^([^\[]*)\[\d+\]\{([^\}]+)\}$', key)
                    if tab_key_match:
                        actual_key = tab_key_match.group(1).strip()
                        fields = [f.strip() for f in tab_key_match.group(2).split(",")]
                        rows = []
                        for i in range(curr_idx + 1, item_end + 1):
                            row_vals = split_csv_line(lines[i][1])
                            obj_item = {}
                            for idx, f in enumerate(fields):
                                val = row_vals[idx] if idx < len(row_vals) else None
                                obj_item[f] = val
                            rows.append(obj_item)
                        obj[actual_key] = rows
                        curr_idx = next_idx
                        continue
                    
                    if next_idx > curr_idx + 1:
                        nested_res = parse_block(curr_idx + 1, item_end)
                        if isinstance(nested_res, dict) and len(nested_res) == 1 and list(nested_res.keys())[0] == "":
                            obj[key] = nested_res[""]
                        else:
                            obj[key] = nested_res
                    else:
                        obj[key] = parse_val(val_str)
                    
                    curr_idx = next_idx
                else:
                    curr_idx += 1
            else:
                curr_idx += 1
        return obj
    
    return parse_block(0, len(lines) - 1)
