"""bind 파라미터 탐지와 bind_set 구성 유틸."""

import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any


_BIND_TOKEN_PATTERN = re.compile(r"[#$]\{\s*([^}]+?)\s*\}")
_IF_TEST_PATTERN = re.compile(r"<if\b[^>]*\btest\s*=\s*['\"](.*?)['\"][^>]*>", re.IGNORECASE | re.DOTALL)
_IDENTIFIER_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_\.]*)\b")
_TEST_LITERAL_COMPARE_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_\.]*)\s*(==|=|eq|!=|<>|ne)\s*('([^']*)'|\"([^\"]*)\"|true|false|null)",
    re.IGNORECASE,
)
_TEST_NULL_COMPARE_PATTERN = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_\.]*)\s*(==|=|eq|!=|<>|ne)\s*null\b",
    re.IGNORECASE,
)

_RESERVED_WORDS = {
    "and",
    "or",
    "not",
    "null",
    "true",
    "false",
    "eq",
    "ne",
    "gt",
    "ge",
    "lt",
    "le",
    "empty",
    "instanceof",
    "new",
    "in",
}


def _normalize_param_name(token: str) -> str:
    """`#{dto.id}` 형태를 최종 bind 키(`id`)로 정규화한다."""
    cleaned = token.strip()
    if not cleaned:
        return ""
    for splitter in [",", " ", "?", ":", "=", "!", ">", "<", "+", "-", "*", "/", ")", "("]:
        if splitter in cleaned:
            cleaned = cleaned.split(splitter)[0]
    return cleaned.strip().split(".")[-1]


def extract_bind_param_names(sql_text: str) -> list[str]:
    """MyBatis placeholder에서 중복 없는 bind 파라미터명을 추출한다."""
    if not sql_text:
        return []
    names: list[str] = []
    seen = set()
    for match in _BIND_TOKEN_PATTERN.finditer(sql_text):
        name = _normalize_param_name(match.group(1))
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item and item not in seen:
                merged.append(item)
                seen.add(item)
    return merged


def _extract_if_param_groups(sql_text: str) -> list[list[str]]:
    """`<if test='...'>` 조건식을 분석해 분기 커버리지 그룹을 추출한다."""
    if not sql_text:
        return []
    groups: list[list[str]] = []
    for match in _IF_TEST_PATTERN.finditer(sql_text):
        condition = match.group(1)
            # 따옴표 리터럴은 파라미터가 아니므로 제거한다.
        condition = re.sub(r"'[^']*'|\"[^\"]*\"", " ", condition)
        group: list[str] = []
        seen = set()
        for ident in _IDENTIFIER_PATTERN.findall(condition):
            lowered = ident.lower()
            if lowered in _RESERVED_WORDS:
                continue
            if ident.isdigit():
                continue
            # `dto.status -> status` 형태로 꼬리 식별자를 유지한다.
            normalized = _normalize_param_name(ident)
            if normalized and normalized not in seen:
                group.append(normalized)
                seen.add(normalized)
        if group:
            groups.append(group)
    return groups


def _extract_test_param_names(sql_text: str) -> list[str]:
    """<if>/<when> test expression에서 조건 제어 파라미터를 추출한다."""
    condition = re.sub(r"'[^']*'|\"[^\"]*\"", " ", sql_text or "")
    names: list[str] = []
    seen: set[str] = set()
    for ident in _IDENTIFIER_PATTERN.findall(condition):
        lowered = ident.lower()
        if lowered in _RESERVED_WORDS:
            continue
        if ident.isdigit():
            continue
        normalized = _normalize_param_name(ident)
        if normalized and normalized not in seen:
            names.append(normalized)
            seen.add(normalized)
    return names


def _extract_all_test_param_names(sql_text: str) -> list[str]:
    names: list[str] = []
    for _tag, condition, _body in _iter_conditional_blocks(sql_text):
        names = _merge_unique(names, _extract_test_param_names(condition))
    return names


def _extract_if_param_groups(sql_text: str) -> list[list[str]]:
    if not sql_text:
        return []
    groups: list[list[str]] = []
    for _tag, condition, _body in _iter_conditional_blocks(sql_text):
        group = _extract_test_param_names(condition)
        if group:
            groups.append(group)
    return groups


def _first_matching_value(row: dict[str, Any], param_name: str):
    """컬럼 대소문자 차이를 흡수해 bind 이름에 대응하는 값을 찾는다."""
    for key in (param_name, param_name.lower(), param_name.upper()):
        if key in row:
            return row[key]
    for key, value in row.items():
        if str(key).lower() == param_name.lower():
            return value
    return None


def _build_bind_case(param_names: list[str], row: dict[str, Any]) -> dict[str, Any]:
    """조회 1행을 bind 케이스 1건으로 변환한다."""
    return {param: _first_matching_value(row, param) for param in param_names}


def _build_branch_seed_cases(sql_text: str) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for _tag, test_expr, _body in _iter_conditional_blocks(sql_text):
        seed = _seed_case_from_test_expr(test_expr)
        if not seed:
            continue
        signature = tuple(sorted(seed.items()))
        if signature in seen:
            continue
        seeds.append(seed)
        seen.add(signature)
    return seeds


def _seed_case_from_test_expr(test_expr: str) -> dict[str, Any]:
    seed: dict[str, Any] = {}
    for match in _TEST_LITERAL_COMPARE_PATTERN.finditer(test_expr or ""):
        param = _normalize_param_name(match.group(1))
        operator = match.group(2).lower()
        literal = _parse_test_literal(match.group(3))
        if not param:
            continue
        if operator in {"==", "=", "eq"}:
            seed[param] = literal
        elif operator in {"!=", "<>", "ne"} and param not in seed:
            seed[param] = _non_matching_literal(literal)

    for match in _TEST_NULL_COMPARE_PATTERN.finditer(test_expr or ""):
        param = _normalize_param_name(match.group(1))
        operator = match.group(2).lower()
        if not param:
            continue
        if operator in {"==", "=", "eq"}:
            seed[param] = None
        elif operator in {"!=", "<>", "ne"}:
            seed[param] = seed.get(param) or "Y"
    return seed


def _parse_test_literal(raw_value: str) -> Any:
    value = (raw_value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    return value


def _non_matching_literal(value: Any) -> Any:
    if value is None:
        return "Y"
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float, Decimal)):
        return value + 1
    text = str(value)
    return f"{text}__other" if text else "Y"


def _signature_for_case(bind_case: dict[str, Any], if_groups: list[list[str]]) -> tuple:
    """분기 활성/비활성 패턴 시그니처를 계산한다."""
    if not if_groups:
        return tuple((k, bind_case.get(k)) for k in sorted(bind_case.keys()))
    signature = []
    for group in if_groups:
        active = any(bind_case.get(param) is not None for param in group)
        signature.append(active)
    return tuple(signature)


def _value_signature(bind_case: dict[str, Any]) -> tuple:
    """중복 제거용 값 시그니처를 계산한다."""
    return tuple((k, bind_case.get(k)) for k in sorted(bind_case.keys()))


def build_bind_sets(
    tobe_sql: str,
    source_sql: str,
    bind_query_rows: list[dict[str, Any]],
    max_cases: int = 3,
) -> list[dict[str, Any]]:
    """최대 3개의 bind 케이스를 생성한다.

    우선순위:
    1) 분기(<if>) 활성 패턴 다양성
    2) 값 중복이 적은 케이스
    """
    safe_max = max(1, min(max_cases, 3))
    param_names = extract_bind_param_names(source_sql)
    if not param_names:
        param_names = extract_bind_param_names(tobe_sql)
    if not param_names:
        return []

    if_groups = _extract_if_param_groups(source_sql)
    if not if_groups:
        if_groups = _extract_if_param_groups(tobe_sql)
    selected: list[dict[str, Any]] = []
    seen_value_signatures = set()
    seen_if_signatures = set()

    for row in bind_query_rows:
        bind_case = _build_bind_case(param_names, row)
        value_sig = _value_signature(bind_case)
        if value_sig in seen_value_signatures:
            continue

        if_sig = _signature_for_case(bind_case, if_groups)
        should_take = False
        if if_groups:
            should_take = if_sig not in seen_if_signatures
        else:
            should_take = True

        if should_take:
            selected.append(bind_case)
            seen_value_signatures.add(value_sig)
            seen_if_signatures.add(if_sig)
            if len(selected) >= safe_max:
                return selected

    if len(selected) < safe_max:
        for row in bind_query_rows:
            bind_case = _build_bind_case(param_names, row)
            value_sig = _value_signature(bind_case)
            if value_sig in seen_value_signatures:
                continue
            selected.append(bind_case)
            seen_value_signatures.add(value_sig)
            if len(selected) >= safe_max:
                break

    if not selected:
        selected = [{param: None for param in param_names}]

    return selected


def bind_sets_to_json(bind_sets: list[dict[str, Any]]) -> str:
    """bind_set을 프롬프트/DB 저장용 JSON 문자열로 직렬화한다."""
    return json.dumps(bind_sets, ensure_ascii=False, default=_json_default)


def _json_default(value: Any):
    """JSON 직렬화 불가 타입을 안전한 표현으로 변환한다."""
    if value is not None and hasattr(value, "read"):
        value = value.read()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
