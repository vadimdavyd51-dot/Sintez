import re


def parse_script(text, skip_first_lines=0, heading_regex=r"^\s*ЧАСТЬ\s+\d+", read_headings=False):
    """Делит сценарий на части по заголовкам.
    Возвращает ([(название, текст)], [(номер_строки, строка)]) - части и пропущенные строки."""
    skipped = []
    parts = [["Вступление", []]]
    for n, line in enumerate(text.splitlines(), 1):
        if n <= skip_first_lines:
            skipped.append((n, line.strip()))
            continue
        if re.match(heading_regex, line):
            parts.append([line.strip(), []])
            if read_headings:
                parts[-1][1].append(line.strip().rstrip(".") + ".")
            continue
        parts[-1][1].append(line.rstrip())
    result = []
    for title, lines in parts:
        body = "\n".join(lines).strip()
        if body:
            result.append((title, body))
    return result, skipped
