"""エージェントの配線テスト。

TestModel は実際のLLMを呼ばない偽モデルで、登録されたツールを全部呼んでから
ダミーの回答を返す。APIキーも利用枠も使わずに、
「ツールが登録され、呼ばれ、結果がモデルに戻るか」を確かめられる。
"""

from pydantic_ai import DeferredToolRequests
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.test import TestModel

from app.agent import agent, run_quiz_loop, run_with_approval

BASE_TOOLS = {"search_glossary", "get_lecture_summary", "make_quiz"}


def _parts(result, kind):
    return [p for m in result.all_messages() for p in m.parts if isinstance(p, kind)]


def test_base_tools_are_registered_and_called():
    model = TestModel()
    with agent.override(model=model):
        result = agent.run_sync("LoRAとは？")

    offered = {t.name for t in model.last_model_request_parameters.function_tools}
    assert BASE_TOOLS <= offered  # 演習でツールを足しても壊れないよう「含む」で判定

    called = {p.tool_name for p in _parts(result, ToolCallPart)}
    assert BASE_TOOLS <= called
    # 承認が必要なツール（requires_approval=True）は、実行されずに承認待ちになるので戻り値が無い
    waiting = len(result.output.approvals) if isinstance(result.output, DeferredToolRequests) else 0
    assert len(_parts(result, ToolReturnPart)) + waiting == len(_parts(result, ToolCallPart))
    assert result.output


def test_glossary_result_reaches_the_model():
    model = TestModel(call_tools=["search_glossary"])
    with agent.override(model=model):
        result = agent.run_sync("RAGとは？")
    returns = _parts(result, ToolReturnPart)
    assert returns and returns[0].tool_name == "search_glossary"


def test_save_learning_log_waits_for_approval(tmp_path, monkeypatch):
    from app import tools

    log_dir = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", log_dir)
    model = TestModel(call_tools=["save_learning_log"])
    with agent.override(model=model):
        result = agent.run_sync("今日の学習内容を記録して")

    assert isinstance(result.output, DeferredToolRequests)
    assert [call.tool_name for call in result.output.approvals] == ["save_learning_log"]
    assert not list(log_dir.glob("*.md"))


def test_save_learning_log_only_writes_after_user_approval(tmp_path, monkeypatch):
    from app import tools

    log_dir = tmp_path / "learning_log"
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", log_dir)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    model = TestModel(call_tools=["save_learning_log"])
    with agent.override(model=model):
        result = run_with_approval(agent, "今日の学習内容を記録して", model)

    assert result.output
    assert len(list(log_dir.glob("*.md"))) == 1


def _run_quiz_loop_with_responses(tmp_path, monkeypatch, save_response):
    from app import tools

    monkeypatch.setattr(
        tools,
        "load_glossary",
        lambda: [{"lecture": 0, "term": "試験語", "definition": "試験定義"}],
    )
    monkeypatch.setattr(tools, "LEARNING_LOG_DIR", tmp_path / "learning_log")
    model = TestModel(
        call_tools=["make_quiz"],
        custom_output_text="正解です。試験定義が正しい説明です。",
    )
    responses = iter(["試験定義", save_response])
    prompts = []

    def input_response(prompt):
        prompts.append(prompt)
        if prompt.startswith("あなたの回答"):
            model.call_tools = []
        return next(responses)

    monkeypatch.setattr("builtins.input", input_response)
    first_result = agent.run_sync("確認問題を出して", model=model)
    return run_quiz_loop(agent, first_result, model), prompts


def test_quiz_loop_grades_answer_and_does_not_save_when_declined(tmp_path, monkeypatch, capsys):
    result, prompts = _run_quiz_loop_with_responses(tmp_path, monkeypatch, "n")

    output = capsys.readouterr().out
    assert "問題:「試験語」の意味は？" in output
    assert "正解です。試験定義が正しい説明です。" in output
    assert prompts == ["あなたの回答: ", "この問題と解答を learning_log/ に保存しますか？ [y/N]: "]
    assert result.output
    assert not list((tmp_path / "learning_log").glob("*.md"))


def test_quiz_loop_saves_only_after_confirmation(tmp_path, monkeypatch, capsys):
    result, prompts = _run_quiz_loop_with_responses(tmp_path, monkeypatch, "yes")

    capsys.readouterr()
    assert prompts[-1] == "この問題と解答を learning_log/ に保存しますか？ [y/N]: "
    assert result.output
    saved_files = list((tmp_path / "learning_log").glob("*.md"))
    assert len(saved_files) == 1
    saved_entry = saved_files[0].read_text(encoding="utf-8")
    assert "問題:「試験語」の意味は？" in saved_entry
    assert "正解: 試験定義" in saved_entry
    assert "あなたの回答: 試験定義" in saved_entry
    assert "正解です。試験定義が正しい説明です。" in saved_entry
