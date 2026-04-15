"""
update_profile skill: manages the user's living profile (CONTEXT.md).

Handles add/remove/update of structured facts so the profile stays
clean and contradiction-free. CONTEXT.md is injected into every system
prompt, so it should stay small and only contain core facts.
"""

import os

_CONTEXT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "CONTEXT.md")

# Valid sections — must match CONTEXT.md headings
_VALID_SECTIONS = {"Preferences", "Schedule", "Routines", "Work", "Personal", "Education", "Health", "Goals"}

# Map common LLM hallucinated sections to valid ones
_SECTION_ALIASES = {
    "fitness": "Health",
    "gym": "Health",
    "exercise": "Health",
    "habits": "Routines",
    "meetings": "Schedule",
    "standup": "Schedule",
    "calendar": "Schedule",
    "recurring": "Schedule",
    "job": "Work",
    "team": "Work",
    "projects": "Work",
    "settings": "Preferences",
    "defaults": "Preferences",
    "school": "Education",
    "university": "Education",
    "classes": "Education",
    "courses": "Education",
    "bio": "Personal",
    "about": "Personal",
    "info": "Personal",
    "family": "Personal",
    "relationships": "Personal",
    "pets": "Personal",
    "targets": "Goals",
    "objectives": "Goals",
    "plans": "Goals",
}


def _normalize_section(section: str) -> str:
    """Map LLM-provided section to a valid CONTEXT.md section."""
    if section in _VALID_SECTIONS:
        return section
    # Check aliases
    lower = section.lower().strip()
    if lower in _SECTION_ALIASES:
        return _SECTION_ALIASES[lower]
    # Check case-insensitive match
    for valid in _VALID_SECTIONS:
        if valid.lower() == lower:
            return valid
    # Default to Routines as safest catch-all
    print(f"  [update_profile] WARNING: unknown section '{section}', defaulting to Routines")
    return "Routines"


def _read_profile() -> str:
    if os.path.exists(_CONTEXT_PATH):
        with open(_CONTEXT_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _write_profile(content: str) -> None:
    with open(_CONTEXT_PATH, "w", encoding="utf-8") as f:
        f.write(content)


def _find_section(lines: list[str], section: str) -> tuple[int, int]:
    """Find (start, end) indices for a ## Section.

    start = heading line index (-1 if not found)
    end   = index of the next heading or len(lines)
    """
    section_lower = section.lower().strip()
    start = -1
    end = len(lines)

    for i, line in enumerate(lines):
        if line.startswith("## ") and line[3:].strip().lower() == section_lower:
            start = i
        elif start != -1 and line.startswith("## "):
            end = i
            break

    return start, end


def _insert_pos(lines: list[str], section_start: int, section_end: int) -> int:
    """Find the right position to insert a new bullet inside a section.

    Returns the index right after the last non-empty line in the section,
    so new items appear directly after existing content, before any blank
    lines or the next heading.
    """
    last_content = section_start  # at minimum, right after the heading
    for i in range(section_start + 1, section_end):
        if lines[i].strip():
            last_content = i
    return last_content + 1


def execute(action: str, section: str, content: str) -> str:
    """Add, remove, or update a line in the user's profile."""
    section = _normalize_section(section)
    profile = _read_profile()
    lines = profile.split("\n") if profile else []

    section_start, section_end = _find_section(lines, section)

    if action == "add":
        new_line = f"- {content}" if not content.startswith("- ") else content

        if section_start == -1:
            # Section doesn't exist — append at end
            # Strip trailing blank lines, add separator, heading, content
            while lines and not lines[-1].strip():
                lines.pop()
            lines.append("")
            lines.append(f"## {section}")
            lines.append(new_line)
            lines.append("")
        else:
            # Check for duplicate
            for i in range(section_start + 1, section_end):
                if content.lower() in lines[i].lower():
                    return f"Already in profile: {lines[i].strip()}"
            # Insert right after last content line in section
            pos = _insert_pos(lines, section_start, section_end)
            lines.insert(pos, new_line)

        _write_profile("\n".join(lines))
        print(f"  [update_profile] ADD '{content}' to [{section}]")
        return f"Added to {section}: {content}"

    elif action == "remove":
        if section_start == -1:
            return f"Section '{section}' not found in profile."

        content_words = set(content.lower().replace("-", "").replace(":", "").split())
        removed = False
        new_lines = []
        for i, line in enumerate(lines):
            if section_start < i < section_end and line.strip():
                line_words = set(line.lower().replace("-", "").replace(":", "").split())
                overlap = len(content_words & line_words)
                # Match if substring hit OR enough word overlap
                if content.lower() in line.lower() or overlap >= min(2, len(content_words)):
                    removed = True
                    print(f"  [update_profile] REMOVE '{line.strip()}' from [{section}]")
                    continue
            new_lines.append(line)

        if not removed:
            return f"No matching line found in [{section}] for: {content}"

        _write_profile("\n".join(new_lines))
        return f"Removed from {section}: {content}"

    elif action == "update":
        if section_start == -1:
            return execute("add", section, content)

        # Find the best matching line by word overlap
        content_words = set(content.lower().split())
        best_idx = -1
        best_overlap = 0

        for i in range(section_start + 1, section_end):
            if not lines[i].strip():
                continue
            line_words = set(lines[i].lower().replace("-", "").split())
            overlap = len(content_words & line_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = i

        new_line = f"- {content}" if not content.startswith("- ") else content

        if best_idx != -1 and best_overlap >= 1:
            old = lines[best_idx].strip()
            lines[best_idx] = new_line
            _write_profile("\n".join(lines))
            print(f"  [update_profile] UPDATE [{section}] '{old}' → '{new_line}'")
            return f"Updated in {section}: {old} → {content}"
        else:
            # No match — add
            pos = _insert_pos(lines, section_start, section_end)
            lines.insert(pos, new_line)
            _write_profile("\n".join(lines))
            print(f"  [update_profile] ADD (no match) '{content}' to [{section}]")
            return f"Added to {section}: {content}"

    else:
        return f"Unknown action: {action}. Use 'add', 'remove', or 'update'."
