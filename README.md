# onlysqlconv

`onlysqlconv`는 Oracle/MyBatis 기반 SQL 이관과 검증을 자동화하기 위한 Supervisor 기반 파이프라인입니다. DB의 작업 테이블에서 이관 대상 정보를 읽고, LLM을 사용해 TO-BE SQL과 검증 SQL을 생성한 뒤, 실제 Oracle 실행 결과를 기준으로 `PASS`/`FAIL` 상태를 판단합니다.

이 문서는 현재 코드 기준의 동작을 설명합니다. 예전 bind metadata/hint 방식이나 deterministic MyBatis materializer 방식은 현재 경로에서 제거되었습니다.

## 전체 구조

```text
main.py
  -> Supervisor Agent
      -> Migration Agent
      -> SQL Conversion Agent
      -> SQL Tuning Agent
```

Supervisor는 각 Agent를 순차적으로 실행하면서 DB 작업 상태를 갱신합니다.

- Migration Agent: `NEXT_MIG_INFO`와 관련 상세 테이블을 기준으로 테이블/컬럼 이관 SQL을 생성하고 실행합니다.
- SQL Conversion Agent: `NEXT_SQL_INFO`의 MyBatis/from SQL을 TO-BE SQL로 변환하고 row count 기반 검증을 수행합니다.
- SQL Tuning Agent: baseline TO-BE SQL 검증 이후, 필요하면 RAG/tuning rule 기반으로 TO-BE SQL을 개선하고 다시 검증합니다.

## 패키지 구조

프로젝트는 크게 실행 진입점, Streamlit UI, DB/LLM 기반 서버 로직, 운영 스크립트, 테스트로 나뉩니다.

```text
onlysqlconv-master/
  README.md
  requirements.txt
  main.py
  app/
  scripts/
  server/
  tests/
```

### 루트

```text
main.py
  Supervisor Agent를 시작하는 메인 실행 파일입니다.

requirements.txt
  Python 의존성 목록입니다.

README.md
  현재 SQL Conversion, prompt 흐름, 실행 방법, 패키지 구조를 설명하는 문서입니다.
```

### app

Streamlit 기반 운영/모니터링 화면입니다.

```text
app/
  app.py
  pages/
    dashboard.py
    mig_monitor.py
    sql_monitor.py
    tuning_monitor.py
    job_detail.py
    rag_manager_page.py
    system_health.py
    settings_page.py
  utils/
    agent_control.py
    db.py
    env_manager.py
    rag_db.py
    rag_manager.py
```

역할:

- `app/app.py`: Streamlit 앱 진입점입니다.
- `app/pages/dashboard.py`: 전체 작업 현황을 보여주는 대시보드입니다.
- `app/pages/mig_monitor.py`: Migration Agent 작업 상태를 모니터링합니다.
- `app/pages/sql_monitor.py`: SQL Conversion 작업 상태와 결과를 확인합니다.
- `app/pages/tuning_monitor.py`: SQL Tuning 결과와 상태를 확인합니다.
- `app/pages/job_detail.py`: 개별 job의 상세 SQL, bind set, test SQL, 로그를 확인하는 화면입니다.
- `app/pages/rag_manager_page.py`: RAG/tuning rule 관련 데이터를 관리합니다.
- `app/pages/system_health.py`: DB, LLM, agent runtime 상태를 확인합니다.
- `app/pages/settings_page.py`: 환경 설정 값을 확인하거나 관리하는 화면입니다.
- `app/utils/agent_control.py`: Agent process 제어 유틸리티입니다.
- `app/utils/db.py`: Streamlit 화면에서 사용하는 DB 연결 유틸리티입니다.
- `app/utils/env_manager.py`: `.env` 값 조회/관리 유틸리티입니다.
- `app/utils/rag_db.py`, `app/utils/rag_manager.py`: RAG 관리 화면에서 사용하는 DB/관리 로직입니다.

### scripts

운영 보조 스크립트입니다.

```text
scripts/
  _bootstrap.py
  init_db.py
  create_sql_rules_table.py
  seed_mig_rules.py
  list_mapping_rules.py
  generate_diagrams.py
```

역할:

- `scripts/_bootstrap.py`: 스크립트 실행 시 프로젝트 import path를 맞추는 bootstrap 코드입니다.
- `scripts/init_db.py`: 초기 DB object 또는 기본 데이터를 준비하는 스크립트입니다.
- `scripts/create_sql_rules_table.py`: SQL/tuning rule 관련 테이블을 생성하는 스크립트입니다.
- `scripts/seed_mig_rules.py`: migration rule seed 데이터를 적재합니다.
- `scripts/list_mapping_rules.py`: 현재 mapping rule을 조회하고 확인합니다.
- `scripts/generate_diagrams.py`: 문서/분석용 다이어그램 생성을 돕는 스크립트입니다.

### server

실제 agent, service, repository, prompt 로직이 들어 있는 핵심 패키지입니다.

```text
server/
  agents/
  config/
  core/
  repositories/
  services/
  tools/
```

#### server/agents

Agent 단위의 graph/orchestrator/state가 있는 영역입니다.

```text
server/agents/
  supervisor/
    agent.py
    graph.py
    state.py
  migration/
    orchestrator.py
    graph.py
    scheduler.py
    executor.py
    verifier.py
    sql_utils.py
    state.py
  sql_conversion/
    agent.py
  sql_tuning/
    agent.py
```

역할:

- `server/agents/supervisor/agent.py`: 전체 agent 실행을 총괄합니다.
- `server/agents/supervisor/graph.py`: Supervisor workflow graph를 구성합니다.
- `server/agents/supervisor/state.py`: Supervisor 실행 상태 모델입니다.
- `server/agents/migration/orchestrator.py`: migration 작업의 전체 흐름을 조율합니다.
- `server/agents/migration/graph.py`: migration workflow graph를 구성합니다.
- `server/agents/migration/scheduler.py`: migration 대상 작업을 선택하고 스케줄링합니다.
- `server/agents/migration/executor.py`: 생성된 migration SQL을 실행합니다.
- `server/agents/migration/verifier.py`: migration 결과를 검증합니다.
- `server/agents/migration/sql_utils.py`: migration SQL 처리 보조 함수입니다.
- `server/agents/migration/state.py`: migration workflow 상태 모델입니다.
- `server/agents/sql_conversion/agent.py`: SQL Conversion agent wrapper입니다.
- `server/agents/sql_tuning/agent.py`: SQL Tuning agent wrapper입니다.

#### server/config

환경 설정과 prompt template이 있는 영역입니다.

```text
server/config/
  settings.py
  prompts/
    migration_prompt.json
    planner_prompt.json
    tobe_sql_prompt.json
    tobe_sql_tuning_prompt.json
    bind_sql_prompt.json
    bind_sql_final_retry_prompt.json
    test_sql_prompt.json
    test_sql_final_retry_prompt.json
```

역할:

- `server/config/settings.py`: 환경 변수 기반 설정을 로드합니다.
- `migration_prompt.json`: migration SQL 생성을 위한 prompt입니다.
- `planner_prompt.json`: planning 단계에서 사용하는 prompt입니다.
- `tobe_sql_prompt.json`: MyBatis/from SQL을 TO-BE SQL로 변환하는 prompt입니다.
- `tobe_sql_tuning_prompt.json`: 생성된 TO-BE SQL을 tuning rule 기반으로 개선하는 prompt입니다.
- `bind_sql_prompt.json`: bind 값 후보를 DB에서 추출하는 일반 Bind SQL prompt입니다.
- `bind_sql_final_retry_prompt.json`: 마지막 3/3 재시도에서 동적 태그 내부 parameter를 제외하고 정적 필수 bind parameter만 추출하는 prompt입니다.
- `test_sql_prompt.json`: source/target SQL row count 비교용 일반 Test SQL을 생성하는 prompt입니다.
- `test_sql_final_retry_prompt.json`: 마지막 3/3 재시도에서 동적 태그 조건 평가를 우회하는 Test SQL을 생성하는 prompt입니다.

#### server/core

여러 영역에서 공통으로 사용하는 infrastructure 코드입니다.

```text
server/core/
  db.py
  db_migration.py
  exceptions.py
  llm.py
  logger.py
```

역할:

- `server/core/db.py`: Oracle DB 연결과 기본 실행 유틸리티입니다.
- `server/core/db_migration.py`: migration DB 처리에서 사용하는 공통 DB 로직입니다.
- `server/core/exceptions.py`: 서비스 전역에서 사용하는 custom exception입니다.
- `server/core/llm.py`: 공통 LLM 설정 또는 호출 보조 로직입니다.
- `server/core/logger.py`: 공통 logger 설정입니다.

#### server/repositories

DB 테이블에 접근하는 repository 계층입니다. Agent/service는 가능하면 이 계층을 통해 DB 상태를 읽고 씁니다.

```text
server/repositories/
  migration/
    repository.py
    history_repository.py
  sql/
    mapper_repository.py
    result_repository.py
  supervisor/
    metrics_repository.py
```

역할:

- `server/repositories/migration/repository.py`: migration 대상과 rule 정보를 조회/갱신합니다.
- `server/repositories/migration/history_repository.py`: migration 실행 이력 저장/조회 로직입니다.
- `server/repositories/sql/mapper_repository.py`: SQL Conversion 대상, mapping rule, skip 조건 등을 조회합니다.
- `server/repositories/sql/result_repository.py`: TO-BE SQL, BIND_SQL, BIND_SET, TEST_SQL, 상태 값을 저장합니다.
- `server/repositories/supervisor/metrics_repository.py`: Agent 실행 지표를 저장합니다.

#### server/services/migration

Migration Agent에서 사용하는 service 계층입니다.

```text
server/services/migration/
  domain_models.py
  llm_client.py
  prompt_service.py
```

역할:

- `domain_models.py`: migration 관련 데이터 모델입니다.
- `llm_client.py`: migration SQL 생성을 위한 LLM 호출 client입니다.
- `prompt_service.py`: migration prompt template 로딩과 렌더링을 담당합니다.

#### server/services/sql

SQL Conversion과 SQL Tuning의 핵심 service 계층입니다.

```text
server/services/sql/
  agents.py
  batch_scheduler.py
  binding_service.py
  db_runtime.py
  domain_models.py
  llm_service.py
  prompt_service.py
  sql_formatting_service.py
  tobe_sql_tuning_service.py
  validation_service.py
  xml_parser_service.py
  workflow/
    graph.py
    state.py
  data/
    rag/
      tobe_rule_catalog.json
    rules/
      universal_tuning_rules.json
  PROMPT_DEBUG_SNIPPET.md
  SQL_FORMATTING_GUIDE.md
```

역할:

- `agents.py`: SQL Conversion과 SQL Tuning의 실행 흐름을 조율합니다. TO-BE SQL 생성, Bind SQL 실행 여부 판단, Test SQL 검증, tuning 검증 흐름이 여기에 모입니다.
- `batch_scheduler.py`: SQL 작업 batch 실행을 스케줄링합니다.
- `binding_service.py`: bind parameter 존재 여부 감지와 `BIND_SET` JSON 생성을 담당합니다.
- `db_runtime.py`: SQL Conversion 실행 중 필요한 DB runtime helper입니다.
- `domain_models.py`: SQL job, mapping rule 등 SQL service에서 사용하는 데이터 모델입니다.
- `llm_service.py`: TO-BE SQL, Bind SQL, Test SQL, Tuning SQL 생성을 위한 LLM 호출 wrapper입니다.
- `prompt_service.py`: SQL prompt JSON을 로드하고 message payload로 렌더링합니다.
- `sql_formatting_service.py`: SQL formatting 및 후처리 보조 로직입니다.
- `tobe_sql_tuning_service.py`: tuning rule 로딩, RAG 검색, tuning example context 생성을 담당합니다.
- `validation_service.py`: Bind SQL과 Test SQL을 실행하고 row count 검증 결과를 판정합니다.
- `xml_parser_service.py`: MyBatis mapper XML을 파싱해 `NEXT_SQL_INFO`에 적재합니다.
- `workflow/graph.py`: SQL Conversion/Tuning workflow graph를 구성합니다.
- `workflow/state.py`: SQL workflow 실행 상태 모델입니다.
- `data/rag/tobe_rule_catalog.json`: TO-BE SQL tuning에 사용하는 RAG rule catalog입니다.
- `data/rules/universal_tuning_rules.json`: 모든 tuning에 공통으로 적용하는 규칙 목록입니다.
- `PROMPT_DEBUG_SNIPPET.md`: prompt 렌더링 결과를 파일로 확인하기 위한 임시 debug snippet입니다.
- `SQL_FORMATTING_GUIDE.md`: SQL formatting 관련 운영 가이드입니다.

#### server/tools

Agent graph에서 호출할 수 있는 tool wrapper 영역입니다.

```text
server/tools/
  context.py
  migration.py
  sql_conversion.py
  sql_tuning.py
```

역할:

- `context.py`: tool 호출에 필요한 공통 context를 제공합니다.
- `migration.py`: Migration Agent용 tool wrapper입니다.
- `sql_conversion.py`: SQL Conversion Agent용 tool wrapper입니다.
- `sql_tuning.py`: SQL Tuning Agent용 tool wrapper입니다.

### tests

테스트 코드 영역입니다.

```text
tests/
  test_xml_parser_service.py
```

역할:

- `test_xml_parser_service.py`: MyBatis XML parser와 관련된 회귀 테스트입니다.


## SQL Conversion 흐름

SQL Conversion Agent는 `server/services/sql/agents.py`의 `TobeSqlGenerationAgent`를 중심으로 동작합니다.

1. `NEXT_SQL_INFO`에서 변환 대상 SQL job을 읽습니다.
2. `tobe_sql_prompt.json`을 사용해 원본 SQL을 TO-BE SQL로 변환합니다.
3. 원본 SQL 또는 생성된 TO-BE SQL에서 bind parameter 존재 여부를 감지합니다.
4. bind parameter가 없으면 Bind SQL 단계를 건너뛰고 `bind_set_json_for_test`를 `[{}]`로 설정합니다.
5. bind parameter가 있으면 `bind_sql_prompt.json`으로 Bind SQL을 생성합니다.
6. 생성된 Bind SQL을 Oracle에서 실행하고, 반환 row를 최대 3개의 bind case로 정리합니다.
7. `test_sql_prompt.json`에 source SQL, target SQL, bind set 등을 전달해 Test SQL을 생성합니다.
8. Test SQL을 실행해 `CASE_NO`, `FROM_COUNT`, `TO_COUNT` 기준으로 검증합니다.
9. 검증 결과가 통과하면 `PASS`, 불일치하거나 실행 오류가 있으면 retry 또는 `FAIL`로 처리합니다.

## Bind SQL 설계

현재 Bind SQL은 “실제 검증에 필요한 bind 값 후보를 DB에서 뽑는 SQL”을 LLM이 생성하는 단계입니다.

중요한 점은 bind parameter 목록을 프롬프트에 metadata로 넘기지 않는다는 것입니다. 코드에서는 bind parameter가 존재하는지 여부만 판단하고, 실제 어떤 컬럼을 어떤 alias로 뽑을지는 `bind_sql_prompt.json`에서 LLM이 판단합니다.

### bind parameter 감지 기준

`server/services/sql/binding_service.py`의 `extract_bind_param_names()`는 Bind SQL 단계를 실행할지 결정하기 위한 최소 감지만 수행합니다.

감지 대상:

- `#{param}`
- `${param}`
- `<foreach collection="ids" item="id"> ... </foreach>`의 `collection` 값
- `<if test="..."></if>` 조건식 안의 식별자
- `<when test="..."></when>` 조건식 안의 식별자

예시:

```xml
<foreach collection="userIds" item="userId">
  #{userId}
</foreach>
```

위 경우 실제 반복 item인 `userId`가 아니라 외부에서 넘어오는 collection parameter인 `userIds`를 bind parameter로 봅니다.

### Bind SQL 스킵

bind parameter가 감지되지 않으면 다음처럼 처리합니다.

```text
bind_sql = ""
bind_set_for_db = None
bind_set_json_for_test = "[{}]"
```

즉, bind가 없는 SQL은 Bind SQL을 생성하거나 실행하지 않고 바로 Test SQL 생성 단계로 넘어갑니다.

### BIND_SET 구성

Bind SQL 실행 결과 row의 column alias가 최종 `BIND_SET`의 key가 됩니다.

예를 들어 Bind SQL 결과가 다음과 같다면:

```json
[
  {"USER_ID": 100, "STATUS": "Y"}
]
```

최종 bind set은 다음처럼 저장됩니다.

```json
[
  {"USER_ID": 100, "STATUS": "Y"}
]
```

따라서 `bind_sql_prompt.json`은 SELECT alias를 MyBatis parameter 이름과 맞추도록 지시합니다.

## Test SQL 설계

Test SQL은 source SQL과 target SQL을 count 기반으로 비교하는 검증 SQL입니다.

`test_sql_prompt.json`은 다음 책임을 가집니다.

- source SQL의 MyBatis placeholder를 `bind_set_json` 값으로 치환
- target SQL의 placeholder를 `bind_set_json` 값으로 치환
- MyBatis 동적 태그(`<if>`, `<choose>`, `<when>`, `<otherwise>`, `<foreach>`, `<where>`, `<trim>`)를 실행 가능한 Oracle SQL 형태로 해석
- 각 bind case별로 `CASE_NO`, `FROM_COUNT`, `TO_COUNT`를 반환하는 SQL 생성
- 검증용 wrapper 내부에서 불필요한 `ORDER BY` 제거
- 최종 retry에서는 동적 태그 조건 평가를 우회하는 fallback SQL 생성

`mapping_schema_text`는 Test SQL prompt에 전달하지 않습니다. Test SQL 단계에서는 mapping rule 기반으로 SQL을 재구성하지 않고, 이미 생성된 source/target SQL을 검증 가능한 형태로 감싸는 역할에 집중합니다. 또한 `SYSDATE`, `CURRENT_DATE`, `SYSTIMESTAMP`, `TRUNC(SYSDATE)`, `ADD_MONTHS(SYSDATE, ...)`, `TO_DATE(...)`, `DATE 'YYYY-MM-DD'` 같은 날짜/기간 조건은 count가 0으로 치우치는 원인이 되므로 제거하도록 prompt에 명시합니다.

## Retry 정책

SQL Conversion은 최대 3회까지 시도합니다.

재시도 시 `last_error`에는 다음 형태의 context가 들어갑니다.

```text
RETRY_CONTEXT: attempt=2/3; FINAL_RETRY_MODE=OFF; last_error=...
RETRY_CONTEXT: attempt=3/3; FINAL_RETRY_MODE=ON; last_error=...
```

마지막 재시도인 `attempt=3/3`에서는 `FINAL_RETRY_MODE=ON`이 됩니다. 이때 일반 `test_sql_prompt.json` 대신 `test_sql_final_retry_prompt.json`을 사용합니다. final retry prompt는 동적 태그의 조건 평가와 관련 join을 완전히 우회하고, 동적 태그 내부 SQL fragment가 제거된 것처럼 보이는 fallback SQL을 만들도록 지시합니다.

목표는 동적 조건 때문에 검증 SQL 자체가 실패하는 상황에서, 동적 태그 내부 쿼리가 제거된 것처럼 보이는 Test SQL을 생성하는 것입니다.

## 프롬프트 입력

### TO-BE SQL Prompt

파일:

```text
server/config/prompts/tobe_sql_prompt.json
```

전달 값:

- `from_sql`
- `mapping_schema_text`
- `target_schema`
- `last_error`

### Bind SQL Prompt

파일:

```text
server/config/prompts/bind_sql_prompt.json
server/config/prompts/bind_sql_final_retry_prompt.json
```

마지막 재시도(`FINAL_RETRY_MODE=ON`)에서는 `bind_sql_final_retry_prompt.json`을 사용합니다. 이 prompt는 동적 태그 내부 parameter를 아예 bind 후보로 뽑지 않고, 정적 SQL 영역의 필수 bind parameter만 반환하도록 지시합니다.

전달 값:

- `from_sql`
- `from_schema`
- `last_error`

현재는 다음 값을 전달하지 않습니다.

- `bind_param_metadata_json`
- `bind_target_hints_json`
- `tobe_sql`
- `mapping_schema_text`

### Test SQL Prompt

파일:

```text
server/config/prompts/test_sql_prompt.json
```

전달 값:

- `source_sql`
- `target_sql`
- `source_schema`
- `target_schema`
- `bind_set_json`
- `comparison_mode`
- `last_error`

## 주요 파일

```text
server/services/sql/agents.py
  SQL Conversion과 SQL Tuning의 실행 흐름을 조율합니다.

server/services/sql/llm_service.py
  TO-BE SQL, Bind SQL, Test SQL, Tuning SQL 생성을 위한 LLM 호출 wrapper입니다.

server/services/sql/binding_service.py
  bind parameter 존재 여부를 감지하고, Bind SQL 실행 결과를 BIND_SET JSON으로 변환합니다.

server/services/sql/validation_service.py
  Bind SQL/Test SQL을 Oracle에서 실행하고 검증 결과를 판정합니다.

server/services/sql/xml_parser_service.py
  MyBatis mapper XML을 파싱해 NEXT_SQL_INFO에 적재합니다. WITH 절의 CTE 이름은 실제 테이블이 아니므로 TARGET_TABLE에서 제외합니다.

server/services/sql/tobe_sql_tuning_service.py
  tuning rule, RAG 검색, tuning example context를 관리합니다.
```

## 제거된 구조

### bind metadata/hint 방식

이전에는 `build_bind_param_metadata()`로 bind parameter와 조건부 그룹을 분석하고, `bind_param_metadata_json`, `bind_target_hints_json`을 Bind SQL prompt에 넘기는 구조가 있었습니다.

현재는 제거되었습니다. 이유는 다음과 같습니다.

- `<foreach>`처럼 placeholder만으로 parameter를 판단하기 어려운 케이스가 있습니다.
- parameter 추출과 bind SQL 설계를 LLM prompt에 일관되게 맡기는 방향으로 변경했습니다.
- 코드는 bind parameter 존재 여부만 판단하고, 실제 alias 설계는 Bind SQL prompt가 담당합니다.

### MyBatis materializer

`mybatis_materializer_service.py`는 제거되었습니다.

현재 검증 경로에서는 deterministic materializer를 호출하지 않습니다. MyBatis 동적 태그 해석과 bind 치환은 `test_sql_prompt.json`이 생성하는 Test SQL 안에서 처리합니다.

## XML Parser

MyBatis mapper XML을 `NEXT_SQL_INFO`로 적재하기 위한 보조 명령입니다.

```bash
python -m server.services.sql.xml_parser_service all
python -m server.services.sql.xml_parser_service stage1 --source-dir C:\path\to\mapper --output-dir C:\path\to\xml-json
python -m server.services.sql.xml_parser_service stage2 --output-dir C:\path\to\xml-json
python -m server.services.sql.xml_parser_service stage3
python -m server.services.sql.xml_parser_service stage4
```

관련 환경 변수:

```env
MAPPER_XML_SOURCE_DIR=
XML_PARSER_DATA_DIR=server/services/sql/DATA
ACTIVE_SQL_ID_TABLE=
ACTIVE_SQL_ID_COLUMN=SQL_ID
```

## 환경 변수

`.env.example`을 복사해서 `.env`를 만든 뒤 실행 환경에 맞게 값을 채웁니다.

```powershell
Copy-Item .env.example .env
```

주요 항목:

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

RAG_EMBED_BASE_URL=
RAG_EMBED_API_KEY=
RAG_EMBED_MODEL=BAAI/bge-m3
RAG_EMBED_TIMEOUT_SEC=30
TOBE_RULE_CATALOG_PATH=server/services/sql/data/rag/tobe_rule_catalog.json
UNIVERSAL_TUNING_RULES_PATH=server/services/sql/data/rules/universal_tuning_rules.json
TOBE_SQL_TUNING_TOP_K=3
TOBE_SQL_TUNING_MAX_ITERATIONS=1

MAPPER_XML_SOURCE_DIR=
XML_PARSER_DATA_DIR=server/services/sql/DATA
```

## 실행

의존성 설치:

```bash
pip install -r requirements.txt
```

초기 DB 준비:

```bash
python scripts/init_db.py
```

Agent 실행:

```bash
python main.py
```

Streamlit dashboard:

```bash
streamlit run app/app.py
```

## 인코딩 기준

README와 prompt JSON은 UTF-8로 저장합니다. 한국어를 사용해도 문제 없습니다.

운영 기준:

- README는 UTF-8 no BOM을 권장합니다.
- prompt JSON은 loader에서 `utf-8-sig`로 읽기 때문에 BOM 유무와 관계없이 로드 가능합니다.
- 깨진 한글이 보이면 한국어 자체가 문제가 아니라, 이전 저장/열기 과정에서 잘못된 인코딩으로 변환된 것입니다.

## 검증 체크리스트

변경 후 최소 확인 항목:

```bash
python -m json.tool server/config/prompts/bind_sql_prompt.json
python -m json.tool server/config/prompts/test_sql_prompt.json
python -m json.tool server/config/prompts/tobe_sql_prompt.json
```

Python 문법 확인 예시:

```bash
python -m py_compile server/services/sql/agents.py
python -m py_compile server/services/sql/binding_service.py
python -m py_compile server/services/sql/llm_service.py
```
