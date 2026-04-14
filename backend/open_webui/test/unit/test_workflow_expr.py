"""Unit tests for workflow_expr (safe n8n-style expressions)."""

from open_webui.workflow_expr import (
    ExprContext,
    evaluate_expression,
    preprocess_expression,
    substitute_template,
)


def test_preprocess_json_path():
    assert preprocess_expression("$json.age") == "_json_get(__json, 'age')"
    assert preprocess_expression("$json.user.name") == "_json_get(__json, 'user', 'name')"
    assert preprocess_expression("$json") == "__json"


def test_eval_json_age():
    ctx = ExprContext({"age": 20, "name": "Alex"}, 0, [{"age": 20}])
    assert evaluate_expression("={{$json.age}}", ctx) == 20
    assert evaluate_expression("={{$json.age > 18}}", ctx) is True


def test_eval_item_index():
    ctx = ExprContext({}, 3, [])
    assert evaluate_expression("={{$itemIndex}}", ctx) == 3


def test_substitute_string_template():
    ctx = ExprContext({"name": "Alex"}, 0, [])
    assert substitute_template("Hi {{$json.name}}", ctx) == "Hi Alex"


def test_if_split_age_expression():
    """Case 2 style: boolean from comparison."""
    ctx = ExprContext({"age": 15}, 0, [{"age": 15}, {"age": 20}])
    assert evaluate_expression("={{$json.age > 18}}", ctx) is False


def test_input_length():
    ctx = ExprContext({}, 0, [{"a": 1}, {"b": 2}])
    assert evaluate_expression("={{$input.length}}", ctx) == 2


def test_item_index_in_template():
    ctx = ExprContext({"x": 1}, 2, [{}])
    assert substitute_template("ix={{ $itemIndex }}", ctx) == "ix=2"


def test_preprocess_node_bracket():
    assert (
        preprocess_expression('$node["Trigger"].json.userInput') == "__node['Trigger'].json.userInput"
    )


def test_eval_node_ref_json():
    ctx = ExprContext(
        {'x': 1},
        0,
        [{}],
        node={
            'Trigger': {
                'json': {'userInput': 'hello'},
                'items': [{'json': {'userInput': 'hello'}}],
            }
        },
    )
    assert evaluate_expression('={{$node["Trigger"].json.userInput}}', ctx) == 'hello'


def test_substitute_node_template():
    ctx = ExprContext(
        {},
        0,
        [],
        node={'A': {'json': {'n': 2}, 'items': [{'json': {'n': 2}}]}},
    )
    assert substitute_template('v={{$node["A"].json.n}}', ctx) == 'v=2'
