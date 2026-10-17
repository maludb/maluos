"""
Tests for app/helpers/skills.py — pure functions, no DB or LLM needed.
"""

from __future__ import annotations

import hashlib

from app.helpers.skills import (
    build_reindex_params,
    bundle_hash,
    coerce_skill_extraction,
    deterministic_discovery,
    file_sha256,
    materiality_screens,
)


def _f(path: str, content: bytes) -> dict:
    return {"relative_path": path, "file_hash": file_sha256(content)}


class TestBundleHash:
    def test_order_independent(self):
        a = [_f("SKILL.md", b"x"), _f("scripts/run.py", b"y")]
        b = [_f("scripts/run.py", b"y"), _f("SKILL.md", b"x")]
        assert bundle_hash(a) == bundle_hash(b)

    def test_script_edit_changes_hash(self):
        base = [_f("SKILL.md", b"same"), _f("scripts/run.py", b"v1")]
        edited = [_f("SKILL.md", b"same"), _f("scripts/run.py", b"v2")]
        assert bundle_hash(base) != bundle_hash(edited)

    def test_is_sha256_hex(self):
        h = bundle_hash([_f("SKILL.md", b"x")])
        assert len(h) == 64
        int(h, 16)

    def test_canonical_line_format(self):
        content = b"hello"
        fh = hashlib.sha256(content).hexdigest()
        expected = hashlib.sha256(f"{fh}  SKILL.md\n".encode()).hexdigest()
        assert bundle_hash([_f("SKILL.md", content)]) == expected


class TestMaterialityScreens:
    PARENT = {
        "markdown": "# Skill\nDo the thing carefully.",
        "frontmatter_jsonb": {"description": "Does the thing. Use when thinging."},
        "files": [
            {"relative_path": "SKILL.md", "file_hash": "aaa"},
            {"relative_path": "scripts/run.py", "file_hash": "bbb"},
        ],
    }
    NEW_FILES = [
        {"relative_path": "SKILL.md", "file_hash": "ccc"},
        {"relative_path": "scripts/run.py", "file_hash": "bbb"},
    ]

    def test_description_change_is_material(self):
        r = materiality_screens(
            self.PARENT,
            self.PARENT["markdown"],
            {"description": "Does a different thing."},
            self.NEW_FILES,
        )
        assert r["verdict"] == "material"
        assert "frontmatter:description" in r["reasons"]

    def test_allowed_tools_change_is_material(self):
        fm = dict(self.PARENT["frontmatter_jsonb"], **{"allowed-tools": "Bash(git:*)"})
        r = materiality_screens(self.PARENT, self.PARENT["markdown"], fm, self.NEW_FILES)
        assert r["verdict"] == "material"
        assert "frontmatter:allowed-tools" in r["reasons"]

    def test_script_change_is_material(self):
        files = [
            {"relative_path": "SKILL.md", "file_hash": "aaa"},
            {"relative_path": "scripts/run.py", "file_hash": "EDITED"},
        ]
        r = materiality_screens(self.PARENT, self.PARENT["markdown"], self.PARENT["frontmatter_jsonb"], files)
        assert r["verdict"] == "material"
        assert "file:scripts/run.py" in r["reasons"]

    def test_file_added_is_material(self):
        files = [*self.NEW_FILES, {"relative_path": "assets/template.txt", "file_hash": "ddd"}]
        r = materiality_screens(self.PARENT, self.PARENT["markdown"], self.PARENT["frontmatter_jsonb"], files)
        assert r["verdict"] == "material"
        assert "file:assets/template.txt" in r["reasons"]

    def test_whitespace_only_is_non_material(self):
        r = materiality_screens(
            self.PARENT,
            "# Skill\n\n  Do the thing   carefully.\n",
            self.PARENT["frontmatter_jsonb"],
            self.NEW_FILES,
        )
        assert r["verdict"] == "non_material"

    def test_body_text_change_is_gray(self):
        r = materiality_screens(
            self.PARENT,
            "# Skill\nDo the thing very carefully and twice.",
            self.PARENT["frontmatter_jsonb"],
            self.NEW_FILES,
        )
        assert r["verdict"] == "gray"

    def test_skill_md_hash_diff_alone_is_not_a_file_reason(self):
        # SKILL.md content is judged by text, not by its manifest hash.
        r = materiality_screens(
            self.PARENT,
            self.PARENT["markdown"],
            self.PARENT["frontmatter_jsonb"],
            self.NEW_FILES,  # SKILL.md hash differs (aaa -> ccc)
        )
        assert r["verdict"] == "non_material"

    def test_frontmatter_as_json_string(self):
        parent = dict(self.PARENT, frontmatter_jsonb='{"description": "Does the thing. Use when thinging."}')
        r = materiality_screens(parent, self.PARENT["markdown"], {"description": "Other."}, self.NEW_FILES)
        assert r["verdict"] == "material"


class TestDeterministicDiscovery:
    def test_name_tokens_and_description_words(self):
        d = deterministic_discovery(
            "pdf-processing",
            {"description": "Extract text from PDF files. Use when working with PDFs."},
        )
        assert "pdf" in d["keywords"]
        assert "processing" in d["keywords"]
        assert "extract" in d["keywords"]
        assert d["subjects"] == [{"name": "pdf-processing"}]
        assert d["verbs"] == []

    def test_stopwords_excluded(self):
        d = deterministic_discovery("the-helper", {"description": "Use this when you are with it."})
        assert "the" not in d["keywords"]
        assert "when" not in d["keywords"]


class TestCoerceSkillExtraction:
    def test_injects_skill_subject_and_document(self):
        out = coerce_skill_extraction({}, "pdf-processing", "# body", {"description": "D."})
        assert out["document"]["document_type"] == "agent_skill"
        assert out["document"]["content_text"] == "# body"
        subjects = out["subjects"]
        assert subjects[0]["name"] == "pdf-processing"
        assert subjects[0]["type"] == "skill"

    def test_retypes_existing_skill_subject(self):
        out = coerce_skill_extraction(
            {"subjects": [{"key": "s1", "name": "PDF-Processing", "type": "software"}]},
            "pdf-processing",
            "# body",
            {},
        )
        assert len(out["subjects"]) == 1
        assert out["subjects"][0]["type"] == "skill"

    def test_keywords_preserved(self):
        out = coerce_skill_extraction({"keywords": ["pdf"]}, "x", "# b", {})
        assert out["keywords"] == ["pdf"]


class TestBuildReindexParams:
    def test_resolves_ids_dedups_and_trims(self):
        extraction = {
            "subjects": [{"name": "Ubuntu"}, {"name": "ubuntu"}, {"name": "PDF"}, {"name": "  "}],
            "verbs": [{"name": "install"}, {"name": "Install"}, {"name": ""}],
            "keywords": ["setup", "Setup", "  ", "apt"],
        }
        # Only 'ubuntu' is known in the registry -> it carries an id; first-wins
        # keeps the id-bearing form and drops the case-dup.
        out = build_reindex_params(extraction, {"ubuntu": 42})
        assert out["subjects"] == [{"name": "Ubuntu", "id": 42}, {"name": "PDF"}]
        assert out["verbs"] == [{"name": "install"}]
        assert out["keywords"] == ["setup", "apt"]

    def test_no_ids_keeps_names_only(self):
        out = build_reindex_params({"subjects": [{"name": "Topic"}]}, {})
        assert out["subjects"] == [{"name": "Topic"}]

    def test_empty_extraction(self):
        assert build_reindex_params({}, {}) == {"subjects": [], "verbs": [], "keywords": []}

    def test_ignores_malformed_entries(self):
        out = build_reindex_params(
            {"subjects": ["not-a-dict", {"name": "Ok"}], "verbs": [None], "keywords": [1, "k"]},
            {},
        )
        assert out["subjects"] == [{"name": "Ok"}]
        assert out["verbs"] == []
        # non-string keywords are coerced via str(); "1" and "k" both survive
        assert out["keywords"] == ["1", "k"]
