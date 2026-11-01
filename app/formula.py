"""Evaluador seguro de fórmulas para estadísticas avanzadas.

Solo admite números, variables conocidas, + - * /, paréntesis y las funciones min, max, abs.
Una división por cero devuelve None (dato no disponible).
"""
import ast
import operator

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
}
_FUNCS = {"min": min, "max": max, "abs": abs}
MAX_LEN = 300


class FormulaError(ValueError):
    pass


def _parse(formula: str):
    if not formula or len(formula) > MAX_LEN:
        raise FormulaError("La fórmula está vacía o es demasiado larga")
    try:
        return ast.parse(formula.strip(), mode="eval").body
    except SyntaxError as e:
        raise FormulaError(f"Sintaxis no válida: {e.msg}")


def names_used(formula: str):
    names = set()

    def walk(n):
        if isinstance(n, ast.Name):
            names.add(n.id)
        for c in ast.iter_child_nodes(n):
            walk(c)

    walk(_parse(formula))
    return names - set(_FUNCS)


def validate(formula: str, allowed_names):
    """Lanza FormulaError si la fórmula no es válida o usa nombres desconocidos."""
    tree = _parse(formula)
    _check(tree, set(allowed_names))


def _check(n, allowed):
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        _check(n.left, allowed); _check(n.right, allowed)
    elif isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        _check(n.operand, allowed)
    elif isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
        pass
    elif isinstance(n, ast.Name):
        if n.id not in allowed:
            raise FormulaError(f"Variable desconocida: {n.id}")
    elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
        for a in n.args:
            _check(a, allowed)
    else:
        raise FormulaError("Operación no permitida (solo + - * / y min, max, abs)")


def _eval(n, ctx):
    if isinstance(n, ast.Constant):
        return n.value
    if isinstance(n, ast.Name):
        return ctx[n.id]
    if isinstance(n, ast.UnaryOp):
        v = _eval(n.operand, ctx)
        return -v if isinstance(n.op, ast.USub) else v
    if isinstance(n, ast.BinOp):
        return _OPS[type(n.op)](_eval(n.left, ctx), _eval(n.right, ctx))
    if isinstance(n, ast.Call):
        return _FUNCS[n.func.id](*[_eval(a, ctx) for a in n.args])
    raise FormulaError("Operación no permitida")


def compile_formula(formula: str, allowed_names):
    tree = _parse(formula)
    _check(tree, set(allowed_names))

    def run(ctx):
        try:
            return _eval(tree, ctx)
        except (ZeroDivisionError, KeyError, TypeError, ValueError):
            return None

    return run
