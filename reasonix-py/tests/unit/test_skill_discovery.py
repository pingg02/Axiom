from reasonix.skill import discover_skills, format_skill_catalog


def test_discovers_project_skill_metadata_without_loading_full_body(tmp_path):
    skill_dir = tmp_path / ".axiom" / "skills" / "release"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: release-check\n"
        "description: Verify a desktop release safely.\n"
        "---\n"
        "# Instructions\n"
        "Run the complete package validation.\n",
        encoding="utf-8",
    )

    skills = discover_skills(tmp_path)

    project_skill = next(skill for skill in skills if skill.name == "release-check")
    assert project_skill.description == "Verify a desktop release safely."
    assert project_skill.scope == "project"
    catalog = format_skill_catalog([project_skill])
    assert "read its SKILL.md" in catalog
    assert str(skill_file.resolve()) in catalog
    assert "Run the complete package validation" not in catalog
