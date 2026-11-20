"""ツールのテスト（LLMもAPIキーも使わない）。"""

import json

from app import tools


def test_glossary_ids_are_unique_and_related_links_exist():
    terms = tools.load_glossary()
    ids = [t["id"] for t in terms]
    assert len(ids) == len(set(ids))
    for t in terms:
        for r in t["related"]:
            assert r in ids, f"{t['id']} の related に存在しない id: {r}"


def test_search_finds_term_by_name_and_alias():
    for query in ["LoRA", "lora", "Low-Rank Adaptation"]:
        hits = json.loads(tools.search_glossary(query))
        assert hits[0]["term"] == "LoRA", query


def test_search_finds_course_specific_term():
    hits = json.loads(tools.search_glossary("lecNN-start"))
    assert hits[0]["term"] == "lecNN-start タグ"


def test_search_limits_number_of_results():
    hits = json.loads(tools.search_glossary("エージェント"))
    assert 1 <= len(hits) <= tools.MAX_RESULTS


def test_search_reports_not_found():
    assert "見つかりませんでした" in tools.search_glossary("存在しない用語xyz")


def test_lecture_summary():
    assert "エージェント" in tools.get_lecture_summary(3)
    assert "まだありません" in tools.get_lecture_summary(99)


def test_make_quiz_selects_a_term_from_the_requested_lecture(monkeypatch):
    terms = [
        {"lecture": 2, "term": "第2回の用語", "definition": "第2回の定義"},
        {"lecture": 3, "term": "第3回の用語", "definition": "第3回の定義"},
    ]
    monkeypatch.setattr(tools, "load_glossary", lambda: terms)
    monkeypatch.setattr(tools.random, "choice", lambda options: options[0])

    assert tools.make_quiz(3) == "問題:「第3回の用語」の意味は？\n答え:第3回の定義"


def test_make_quiz_reports_when_lecture_has_no_terms(monkeypatch):
    monkeypatch.setattr(tools, "load_glossary", lambda: [])

    assert "第99回" in tools.make_quiz(99)


def test_save_learning_log_writes_entry_to_learning_log_directory(tmp_path, monkeypatch):
    log_dir = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", log_dir)

    result = tools.save_learning_log("今日はエージェントを学んだ。")

    saved_files = list(log_dir.glob("*.md"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == "今日はエージェントを学んだ。"
    assert "保存しました" in result


def test_search_materials_returns_deduplicated_context_in_page_order(monkeypatch):
    def page(number):
        return {
            "page_id": f"lec01-main-p{number:03}",
            "document_id": "lec01-main",
            "lecture": 1,
            "page": number,
            "title": f"ページ{number}",
            "content": f"本文{number}",
        }

    hit_3 = {**page(3), "distance": 0.1, "previous_page": page(2), "next_page": page(4)}
    hit_2 = {**page(2), "distance": 0.2, "previous_page": page(1), "next_page": page(3)}
    monkeypatch.setattr("app.retrieval.search", lambda _query: [hit_3, hit_2])

    result = json.loads(tools.search_materials("質問"))["results"]

    assert [item["page"] for item in result] == [1, 2, 3, 4]
    assert [item["matched"] for item in result] == [False, True, True, False]
    assert [item["distance"] for item in result if item["matched"]] == [0.2, 0.1]
    assert all("previous_page" not in item and "next_page" not in item for item in result)


def test_default_question_of_lecture1_is_answerable_from_glossary():
    """第1回の既定の質問（app.ask）は、第3回のエージェントが用語集で正しく答えられること。"""
    from app.ask import DEFAULT_QUESTION

    assert "3レベル" in DEFAULT_QUESTION
    hits = json.loads(tools.search_glossary("3レベル"))
    assert hits[0]["term"] == "宿題の3レベル"
