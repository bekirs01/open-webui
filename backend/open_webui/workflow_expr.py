"""
n8n-style expressions:
  {{$json.field}}, {{$node["Label"].json.field}}, {{$itemIndex}}, {{$input.length}}
Safe evaluation — no arbitrary eval(); AST whitelist + fixed environment only.
"""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from typing import Any, Optional

_RE_ITEM_INDEX = re.compile(r"\$itemIndex\b")
_RE_INPUT_LEN = re.compile(r"\$input\.length\b")
_RE_INPUT = re.compile(r"\$input\b")
# Dotted paths: $json.a.b (must run before bare $json)
_RE_JSON_DOTTED = re.compile(r"\$json(?:\.\w+)+")
# $node["Human-readable name"] — name may include spaces/parens (from unique key builder)
_RE_NODE_BRACKET = re.compile(r'\$node\["([^"]*)"\]')


def _json_get(obj: Any, *keys: str) -> Any:
    cur: Any = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = getattr(cur, k, None)
    return cur


def _replace_json_paths(expr: str) -> str:
    """Turn $json and $json.a.b into __json / _json_get(__json, 'a', 'b')."""

    def repl_dotted(m: re.Match) -> str:
        full = m.group(0)
        if not full.startswith('$json'):
            return full
        rest = full[5:]
        if not rest.startswith('.'):
            return '__json'
        parts = [p for p in rest[1:].split('.') if p]
        args = ', '.join(repr(p) for p in parts)
        return f'_json_get(__json, {args})'

    s = _RE_JSON_DOTTED.sub(repl_dotted, expr)
    return re.sub(r'\$json\b', '__json', s)


def _replace_input_and_index(expr: str) -> str:
    s = _RE_INPUT_LEN.sub('len(__input)', expr)
    s = _RE_ITEM_INDEX.sub('__item_index', s)
    # $input after .length handled; bare $input last
    s = _RE_INPUT.sub('__input', s)
    return s


def _replace_node_bracket(expr: str) -> str:
    """Turn $node["Label"] into __node[...] using Python repr for the key string."""

    def repl(m: re.Match) -> str:
        name = m.group(1)
        return f'__node[{repr(name)}]'

    return _RE_NODE_BRACKET.sub(repl, expr)


def preprocess_expression(expr: str) -> str:
    """Map n8n-style $-variables to sandbox names."""
    s = (expr or '').strip()
    s = _replace_node_bracket(s)
    s = _replace_json_paths(s)
    s = _replace_input_and_index(s)
    return s


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_CMPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

_ALLOWED_BOOL = {ast.And: lambda a, b: a and b, ast.Or: lambda a, b: a or b}

_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}

_ALLOWED_FUNCS = frozenset({'len', 'str', 'int', 'float', 'bool', 'abs', 'min', 'max', 'round'})


def _safe_eval_ast(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval_ast(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f'Unknown or forbidden name in expression: {node.id}')
        return env[node.id]
    if isinstance(node, ast.Compare):
        parts = [_safe_eval_ast(node.left, env)]
        parts += [_safe_eval_ast(c, env) for c in node.comparators]
        for i, op in enumerate(node.ops):
            if type(op) not in _ALLOWED_CMPS:
                raise ValueError(f'Unsupported comparison op: {type(op).__name__}')
            fn = _ALLOWED_CMPS[type(op)]
            if not fn(parts[i], parts[i + 1]):
                return False
        return True
    if isinstance(node, ast.BoolOp):
        vals = [_safe_eval_ast(v, env) for v in node.values]
        t = type(node.op)
        if t not in _ALLOWED_BOOL:
            raise ValueError('Unsupported boolean op')
        acc = vals[0]
        for v in vals[1:]:
            acc = _ALLOWED_BOOL[t](acc, v)
        return acc
    if isinstance(node, ast.UnaryOp):
        t = type(node.op)
        if t not in _ALLOWED_UNARY:
            raise ValueError('Unsupported unary op')
        return _ALLOWED_UNARY[t](_safe_eval_ast(node.operand, env))
    if isinstance(node, ast.BinOp):
        t = type(node.op)
        if t not in _ALLOWED_BINOPS:
            raise ValueError('Unsupported binary op')
        return _ALLOWED_BINOPS[t](
            _safe_eval_ast(node.left, env),
            _safe_eval_ast(node.right, env),
        )
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name == '_json_get':
                fn = env.get('_json_get')
                if not callable(fn):
                    raise ValueError('_json_get missing from expression env')
                args = [_safe_eval_ast(a, env) for a in node.args]
                return fn(*args)
            if name not in _ALLOWED_FUNCS:
                raise ValueError(f'Call to forbidden function: {name}')
            fn = env.get(name)
            if fn is None or not callable(fn):
                raise ValueError(f'Undefined safe function: {name}')
            args = [_safe_eval_ast(a, env) for a in node.args]
            return fn(*args)
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'get' and len(node.args) <= 2:
            obj = _safe_eval_ast(node.func.value, env)
            key = _safe_eval_ast(node.args[0], env)
            default = _safe_eval_ast(node.args[1], env) if len(node.args) > 1 else None
            if isinstance(obj, dict):
                return obj.get(key, default)
            return default
        raise ValueError('Only simple calls to allowed builtins or dict.get are permitted')
    if isinstance(node, ast.Subscript):
        val = _safe_eval_ast(node.value, env)
        if isinstance(node.slice, ast.Constant):
            idx = node.slice.value
        elif isinstance(node.slice, ast.UnaryOp) and isinstance(node.slice.op, ast.USub):
            idx = -_safe_eval_ast(node.slice.operand, env)
        else:
            idx = _safe_eval_ast(node.slice, env)
        return val[idx]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_eval_ast(elt, env) for elt in node.elts)
    if isinstance(node, ast.List):
        return [_safe_eval_ast(elt, env) for elt in node.elts]
    if isinstance(node, ast.IfExp):
        return (
            _safe_eval_ast(node.body, env)
            if _safe_eval_ast(node.test, env)
            else _safe_eval_ast(node.orelse, env)
        )
    if isinstance(node, ast.Attribute):
        v = _safe_eval_ast(node.value, env)
        attr = node.attr
        if isinstance(v, dict) and attr in v:
            return v[attr]
        raise ValueError(f'Unknown or forbidden attribute: {attr!r}')
    raise ValueError(f'Unsupported syntax in expression: {type(node).__name__}')


@dataclass
class ExprContext:
    """One evaluation context for a single wire row."""

    json: dict[str, Any]
    item_index: int
    input: list[dict[str, Any]]
    #: Map display key -> {'json': first item dict, 'items': full items list} (n8n-style $node).
    node: Optional[dict[str, Any]] = None


def build_eval_env(ctx: ExprContext) -> dict[str, Any]:
    """Sandbox environment for preprocess + AST eval (no __builtins__ tricks)."""
    node_map: dict[str, Any] = ctx.node if isinstance(ctx.node, dict) else {}
    return {
        '__builtins__': {},
        '_json_get': _json_get,
        '__json': ctx.json,
        '__item_index': ctx.item_index,
        '__input': ctx.input,
        '__node': node_map,
        'len': len,
        'str': str,
        'int': int,
        'float': float,
        'bool': bool,
        'abs': abs,
        'min': min,
        'max': max,
        'round': round,
    }


def evaluate_expression(expr: str, ctx: ExprContext) -> Any:
    """
    Evaluate a single expression string (after optional '=' strip).
    Example: "={{$json.age > 18}}", "{{$json.age}}", or "$json.age > 18" after unwrap.
    """
    raw = (expr or '').strip()
    if raw.startswith('='):
        raw = raw[1:].strip()
    if raw.startswith('{{') and raw.endswith('}}'):
        raw = raw[2:-2].strip()
    pre = preprocess_expression(raw)
    tree = ast.parse(pre, mode='eval')
    env = build_eval_env(ctx)
    return _safe_eval_ast(tree, env)


_RE_TEMPLATE = re.compile(r'\{\{([^}]+)\}\}')


def substitute_template(template: str, ctx: ExprContext) -> str:
    """
    Replace {{ ... }} segments. Inner "=expr" or "expr" is evaluated via evaluate_expression.
    """
    if template is None:
        return ''

    def one_segment(inner: str) -> str:
        s = inner.strip()
        try:
            val = evaluate_expression(s, ctx)
        except Exception:
            return ''
        if val is None:
            return ''
        if isinstance(val, bool):
            return 'true' if val else 'false'
        return str(val)

    out: list[str] = []
    pos = 0
    for m in _RE_TEMPLATE.finditer(template):
        out.append(template[pos : m.start()])
        out.append(one_segment(m.group(1)))
        pos = m.end()
    out.append(template[pos:])
    return ''.join(out)


def wire_items_to_json_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract json dict from each wire item."""
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get('json'), dict):
            out.append(it['json'])
        elif isinstance(it, dict):
            out.append(dict(it))
        else:
            out.append({})
    return out
