# 第6回 解答

## 演習

<!-- [tool call] の行は、表示された行をそのまま貼り付けてください。終わらなかった STEP は、空欄のままでかまいません。 -->

- STEP 1 のツールの名前：app.agent:[search_glossary][search_materials][get_lecture_summary][make_quiz][save_learning_log],app.mcp_agent:[glossary_search_glossary]
- STEP 2 の [tool call]：glossary_search_glossary({'query': '3レベル'})
- STEP 3 の [tool call]：fetch_fetch({'url': 'https://modelcontextprotocol.io/'})
- STEP 4 の [tool call]：aws_aws___search_documentation({'search_phrase': 'Amazon S3 バージョニング 概要', 'topics': ['general']}),aws_aws___search_documentation({'topics': ['general'], 'search_phrase': 'Versioning what is Amazon S3 versioning'})
- 気づき・疑問：AWSだとモデルの応答回数が３回になっていてトークン数もふえていた。MCPの仕様をしらないとコストがかさむリスクがある。

## 宿題

<!-- 基礎・実装・発展のどれか1つに取り組めば完了です。 -->

- 取り組んだレベル：実装
- やったこと：MCP サーバーに第3回で作った make_quizを追加した。
- 結果：第９９回のクイズ作成要求には、
申し訳ありません。第99回は対象範囲外（または用語集に存在しない回）のため、クイズを作成することができません。

現在、用語集に登録されているのは以下の回になります。
- 第1回
- 第2回
- 第3回
- 第4回
- 第6回

これらの回のいずれかでクイズを作成してもよろしいでしょうか？ご希望の回があればお知らせください。
と回答された。
第6回のクイズ作成要求には、
問題:「MCPクライアント」の意味は？、
💡 **ヒント：**
Model Context Protocol（MCP）において、サーバー側が提供する機能やツールを、実際に受け取ってモデルに渡したり呼び出したりする「側」のことです。Claude DesktopやCursor、あるいはPydantic AIのエージェントプログラムなどがこれに該当します。

考えてみてくださいね！回答がまとまったら教えてください。
（関係する回：第6回）
が生成された。さらに[tool return] に答え:MCPサーバーに接続し、公開されたツールをモデルに渡して、モデルの指示でツールを呼び出す側。エージェントのプログラム（Pydantic AIの MCPToolset）や、Copilot Chat…が出力された。
問題回答セットは期待通りに作成された。
- 気づき・疑問：MCPサーバー追加したツールもこれまでのハーネスのツールと同じように使うことができた。
