# onlysqlconv

A supervisor-driven Oracle/MyBatis SQL conversion pipeline. It reads migration and SQL conversion jobs from Oracle tables, generates TO-BE SQL with an LLM, builds bind values when needed, validates row counts, and optionally tunes generated SQL.

## Runtime Flow

```text
main.py
  -> Supervisor Agent
      -> Migration Agent
      -> SQL Conversion Agent
      -> SQL Tuning Agent
```

The SQL Conversion Agent flow is:

1. Load a `NEXT_SQL_INFO` job.
2. Generate TO-BE SQL from the original MyBatis/from SQL and selected mapping rules.
3. Detect whether bind parameters exist in the original SQL. Detection includes `#{...}`, `${...}`, `<foreach collection="...">`, and `<if>/<when test="...">` expressions.
4. If no bind parameters are detected, skip Bind SQL and use `[{}]` for test SQL generation.
5. If bind parameters exist, generate Bind SQL from `bind_sql_prompt.json`, execute it, and build up to three bind cases from the returned column aliases.
6. Generate Test SQL from source SQL, target SQL, schemas, bind set JSON, comparison mode, and last error.
7. Execute Test SQL and decide `PASS` or `FAIL` from row-count comparison rows.
8. On the final retry (`attempt=3/3`), prompt context enables final retry mode so dynamic tag conditions and related joins can be bypassed by the Test SQL prompt.

## Prompt Inputs

### TO-BE SQL

`server/config/prompts/tobe_sql_prompt.json` receives:

- `from_sql`
- `mapping_schema_text`
- `target_schema`
- `last_error`

### Bind SQL

`server/config/prompts/bind_sql_prompt.json` receives only:

- `from_sql`
- `from_schema`
- `last_error`

The legacy bind metadata/hint flow has been removed. Bind parameter existence is detected in code only to decide whether the Bind SQL stage should run. Final `BIND_SET` keys come from the Bind SQL result aliases produced by the LLM-generated query.

### Test SQL

`server/config/prompts/test_sql_prompt.json` receives:

- `source_sql`
- `target_sql`
- `source_schema`
- `target_schema`
- `bind_set_json`
- `comparison_mode`
- `last_error`

`mapping_schema_text` is not passed to Test SQL. Test SQL is responsible for bind substitution, MyBatis dynamic tag handling, row-count comparison SQL generation, and final-retry dynamic bypass behavior.

## Important Services

```text
server/services/sql/agents.py
  Coordinates TO-BE generation, optional Bind SQL, Test SQL validation, and tuning.

server/services/sql/llm_service.py
  LLM wrapper for TO-BE SQL, Bind SQL, Test SQL, and tuned SQL prompts.

server/services/sql/binding_service.py
  Detects bind parameters and builds bind-set JSON from Bind SQL result rows.

server/services/sql/validation_service.py
  Executes Bind SQL/Test SQL and evaluates validation rows.

server/services/sql/tobe_sql_tuning_service.py
  Loads tuning rules, retrieves RAG examples, and prepares tuning context.

server/services/sql/xml_parser_service.py
  Parses MyBatis mapper XML into `NEXT_SQL_INFO`; CTE names from WITH clauses are excluded from `TARGET_TABLE`.
```

The deterministic MyBatis materializer module was removed because the current validation path delegates MyBatis materialization to the Test SQL prompt.

## Prompt Files

```text
server/config/prompts/
  bind_sql_prompt.json
  test_sql_prompt.json
  tobe_sql_prompt.json
  tobe_sql_tuning_prompt.json
  migration_prompt.json
  planner_prompt.json
```

Prompt JSON is loaded with `utf-8-sig`, so both BOM and non-BOM UTF-8 JSON files are accepted.

## Environment

Copy `.env.example` to `.env` and fill the runtime values.

```powershell
Copy-Item .env.example .env
```

Common variables:

```env
DB_USER=
DB_PASS=
DB_HOST=localhost
DB_PORT=1521
DB_SID=xe
ORACLE_CLIENT_PATH=
ORACLE_SCHEMA_SRC=
ORACLE_SCHEMA_TGT=

MAPPING_RULE_TABLE=NEXT_MIG_INFO
MAPPING_RULE_DETAIL_TABLE=NEXT_MIG_INFO_DTL
RESULT_TABLE=NEXT_SQL_INFO

LLM_PROVIDER=openai
LLM_API_KEY=
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=
LLM_MAX_TOKENS=4096

TOBE_SQL_TUNING_MAX_ITERATIONS=1
MAPPER_XML_SOURCE_DIR=
XML_PARSER_DATA_DIR=server/services/sql/DATA
```

## Run

```bash
pip install -r requirements.txt
python scripts/init_db.py
python main.py
```

Streamlit dashboard:

```bash
streamlit run app/app.py
```

## XML Parser

```bash
python -m server.services.sql.xml_parser_service all
python -m server.services.sql.xml_parser_service stage1 --source-dir C:\path\to\mapper --output-dir C:\path\to\xml-json
python -m server.services.sql.xml_parser_service stage2 --output-dir C:\path\to\xml-json
python -m server.services.sql.xml_parser_service stage3
python -m server.services.sql.xml_parser_service stage4
```

