"""第3回: Pydantic AI で作る学習支援エージェント。

使い方:
    uv run python -m app.agent "AIE2026の講座で使う「lecNN-start タグ」とは何ですか？"
    uv run python -m app.agent --trace "LoRAとQLoRAの違いは？"   # ツール呼び出しを表示
    uv run python -m app.agent --mcp --trace "LoRAとは？"        # 第5回: ツールを MCP サーバーから受け取る
    uv run python -m app.agent --mcp --list-tools               # 第5回: モデルに見えるツール一覧（APIキー不要）

エージェント = モデル + ループ + ツール。
モデルは tools.py の関数を「ツール」として呼び出し、その結果を見て回答を作る。
第5回では、同じツールを MCP サーバー（app/mcp_server.py）経由で受け取る。
"""

import argparse
import inspect
import json
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.exceptions import ModelHTTPError
from fastmcp import Client
from pydantic_ai.mcp import MCPToolset, StdioTransport
from pydantic_ai.messages import ToolCallPart, ToolReturnPart
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.providers.google import GoogleProvider

from app import tools
from app.config import MODEL, api_error_message, get_api_key

INSTRUCTIONS = """\
あなたはAIエンジニアリング講座（AIE2026）の学習支援エージェントです。
- 用語や講座に固有のことを答える前に、必ず search_glossary で用語集を確認する。
- 回の内容を聞かれたら get_lecture_summary を使う。
- クイズを出すときは make_quiz の結果から問題だけを伝え、正解はユーザーが回答するまで明かさない。
- ユーザーがクイズに回答したら、正解と照らして正誤を判定し、正解と解説を返す。
- クイズの問題・回答・正解・解説は、ユーザーが保存に同意するまで save_learning_log で記録しない。
- 用語集に見つからないことは、推測で断定せず「用語集にはない」と伝える。
- 回答の最後に、関係する回（第N回）を示す。
- 宿題の答えそのものは書かず、考え方のヒントで導く。
"""

# モデルは実行時に渡す（テストではAPIを呼ばない TestModel に差し替えるため）
agent = Agent(instructions=INSTRUCTIONS, output_type=[str, DeferredToolRequests])
agent.tool_plain(tools.search_glossary)
agent.tool_plain(tools.get_lecture_summary)
agent.tool_plain(tools.make_quiz)
agent.tool_plain(tools.save_learning_log, requires_approval=True)

# 第5回: 使う MCP サーバーの設定ファイル。Claude Desktop や Cursor と同じ "mcpServers" 形式
MCP_CONFIG = Path(__file__).resolve().parent / "mcp_servers.json"


def load_mcp_servers(config_path: Path = MCP_CONFIG) -> list[MCPToolset]:
    """設定ファイル（mcpServers 形式）を読み、サーバーごとに接続（MCPToolset）を作る。

    - "command" があれば stdio：サーバーをサブプロセスとして起動する
    - "url" があれば Streamable HTTP：起動済みのサーバーに接続する
    ツール名には「サーバー名_」を付ける（例: glossary_search_glossary）。複数のサーバーに
    同じ名前のツールがあっても区別できるようにするため。

    Pydantic AI には同じことをする load_mcp_toolsets() もある。ここで自分で組み立てているのは、
    古い SDK で作られたサーバー（fetch など）につなぐとき、接続方式の自動判定（"auto"）が
    警告を大量に出すため。"legacy" に固定すると新旧どちらのサーバーにも静かにつながる。
    """
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))["mcpServers"]
    toolsets = []
    for name, spec in config.items():
        if "url" in spec:
            transport = spec["url"]
        else:
            transport = StdioTransport(spec["command"], spec.get("args", []), env=spec.get("env"))
        toolsets.append(MCPToolset(Client(transport, mode="legacy")).prefixed(name))
    return toolsets


def build_mcp_agent(config_path: Path = MCP_CONFIG) -> Agent:
    """第5回: 関数を直接登録する代わりに、MCP サーバーが公開するツールを使うエージェント。INSTRUCTIONS は同じ。"""
    return Agent(instructions=INSTRUCTIONS, toolsets=load_mcp_servers(config_path))


def build_model() -> GoogleModel:
    return GoogleModel(MODEL, provider=GoogleProvider(api_key=get_api_key()))


def print_tools(target: Agent) -> None:
    """モデルに見えているツールの一覧（名前・説明文・引数）を表示する。LLM は呼ばない。

    TestModel（テストで使う偽モデル）にツール一覧を渡し、そこから読み出す。
    MCP サーバーのツールも、第3回の関数ツールも、モデルから見れば同じ形をしている。
    """
    model = TestModel(call_tools=[])
    target.run_sync("ツール一覧", model=model)
    tools_seen = model.last_model_request_parameters.function_tools
    print(f"モデルに見えているツール: {len(tools_seen)} 個")
    for tool in tools_seen:
        print(f"\n[{tool.name}]")
        print("  " + inspect.cleandoc(tool.description or "").replace("\n", "\n  "))
        params = tool.parameters_json_schema.get("properties", {})
        print(f"  引数: {json.dumps(params, ensure_ascii=False)}")


def print_trace(result) -> None:
    """どのツールが、どの引数で呼ばれ、何を返したかを表示する。"""
    print("\n--- trace ---")
    for message in result.all_messages():
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                print(f"[tool call]   {part.tool_name}({part.args})")
            elif isinstance(part, ToolReturnPart):
                print(f"[tool return] {part.tool_name} -> {str(part.content)[:120]}…")
    print(f"[usage] {result.usage}")


def run_with_approval(target: Agent, question: str, model, *, result=None, confirmed=False):
    if result is None:
        result = target.run_sync(question, model=model)
    while isinstance(result.output, DeferredToolRequests):
        requests = result.output
        approvals = {}
        for call in requests.approvals:
            details = call.args if isinstance(call.args, str) else json.dumps(call.args, ensure_ascii=False)
            print(f"\n{call.tool_name} の実行内容:\n{details}")
            if confirmed:
                approvals[call.tool_call_id] = True
            else:
                try:
                    answer = input("learning_log/ に保存しますか？ [y/N]: ").strip().lower()
                except EOFError:
                    answer = ""
                approvals[call.tool_call_id] = answer in {"y", "yes"}
        result = target.run_sync(
            None,
            model=model,
            message_history=result.all_messages(),
            deferred_tool_results=requests.build_results(approvals=approvals),
        )
    return result


def _tool_return(result, tool_name: str) -> str | None:
    for message in result.all_messages():
        for part in message.parts:
            if isinstance(part, ToolReturnPart) and part.tool_name == tool_name:
                return str(part.content)
    return None


def _tool_was_called(result, tool_name: str) -> bool:
    return any(
        isinstance(part, ToolCallPart) and part.tool_name == tool_name
        for message in result.all_messages()
        for part in message.parts
    )


def run_quiz_loop(target: Agent, result, model):
    quiz = _tool_return(result, "make_quiz")
    if quiz is None:
        print(result.output)
        return result
    if not quiz.startswith("問題:"):
        print(quiz)
        return result

    question = quiz.splitlines()[0]
    print(question)
    try:
        user_answer = input("あなたの回答: ").strip()
    except EOFError:
        return result
    if not user_answer:
        return result

    result = target.run_sync(
        f"私の回答: {user_answer}\nこの回答を問題の正解と比較し、正誤と解説を返してください。",
        model=model,
        message_history=result.all_messages(),
    )
    print(result.output)

    try:
        save_answer = input("この問題と解答を learning_log/ に保存しますか？ [y/N]: ").strip().lower()
    except EOFError:
        save_answer = ""
    if save_answer not in {"y", "yes", "はい"}:
        return result

    correct_answer = quiz.splitlines()[1].removeprefix("答え:")
    entry = (
        f"# クイズ学習記録\n\n{question}\n\n"
        f"- 正解: {correct_answer}\n"
        f"- あなたの回答: {user_answer}\n\n"
        f"## 判定と解説\n\n{result.output}\n"
    )
    print(tools.save_learning_log(entry))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="学習支援エージェントに質問する")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--trace", action="store_true", help="ツール呼び出しを表示する")
    parser.add_argument("--mcp", action="store_true", help="第5回: ツールを MCP サーバー（app/mcp_servers.json）から受け取る")
    parser.add_argument("--list-tools", action="store_true", help="モデルに見えるツール一覧を表示して終了する（APIキー不要）")
    args = parser.parse_args()

    target = build_mcp_agent() if args.mcp else agent
    if args.list_tools:
        print_tools(target)
        return
    if not args.question:
        parser.error("質問を指定してください")

    print(f"[model] {MODEL}")
    if args.mcp:
        print("[tools] MCP サーバー（app/mcp_servers.json）")
    try:
        model = build_model()
        result = target.run_sync(args.question, model=model)
        if _tool_was_called(result, "make_quiz"):
            result = run_quiz_loop(target, result, model)
        else:
            result = run_with_approval(target, args.question, model, result=result)
            print(result.output)
    except ModelHTTPError as e:
        print(api_error_message(e.status_code, str(e.body)[:200]))
        raise SystemExit(1)
    if args.trace:
        print_trace(result)


if __name__ == "__main__":
    main()
