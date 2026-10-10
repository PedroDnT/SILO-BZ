"""Guard the instruction-loader byte cap and reachable on-demand entry points."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_root_instructions_fit_the_loader_byte_cap():
    size = len((ROOT / "AGENTS.md").read_bytes())
    assert size < 32 * 1024, f"AGENTS.md is {size} bytes; loader cap is 32 KiB"


def test_reference_detail_is_on_demand_and_reachable_from_entry_points():
    agents = (ROOT / "AGENTS.md").read_text()
    claude = (ROOT / "CLAUDE.md").read_text()
    silo = (ROOT / ".claude/skills/silo/SKILL.md").read_text()
    assert "@docs/agents/dataset-notes.md" not in claude
    assert "@AGENTS.md" in claude
    for name in ("docs/agents/dataset-notes.md", "docs/agents/cursor-cloud.md", "docs/agents/consumers.md"):
        assert name in agents and (ROOT / name).is_file()
    assert "docs/agents/dataset-notes.md" in silo
