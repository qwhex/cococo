# Spec: how cococo should score nested functions

**Status:** Implemented in `2.0.0`
**Affects:** core scoring (`cognitive_complexity/api.py`, `cognitive_complexity/utils/ast.py`), function discovery (`cognitive_complexity/discovery.py`), and reported output
**Version:** `2.0.0` (breaking change to reported numbers)
**Compatibility:** the pre-2.0.0 folding behavior this spec replaces (called "today" / "folded" below) remains available via `cococo --nested=fold` or `get_cognitive_complexity(funcdef, fold_nested=True)`, added in `3.0.0` as a migration aid.

---

## One-paragraph summary

Today cococo *folds* every nested `def`/`async def` into the score of the
function that encloses it. On factory/registry-shaped code — a function whose
body is mostly independent named inner functions (FastAPI/Flask app factories,
Click command groups, decorator factories, dispatch tables of closures) — this
produces a number that does not describe the outer function, is larger than the
sum of the inner functions' own scores (a nesting surcharge), and hides which
inner function is actually hard to read. This spec proposes scoring each **named**
nested function as its own reporting unit (and continuing to fold **lambdas**),
which fixes both the misattribution and the surcharge, and collapses an existing
special case (`is_decorator`) into one uniform rule.

---

## 1. Background: what cognitive complexity is, and how cococo computes it

Cognitive complexity (G. Ann Campbell / SonarSource) measures how hard code is
for a *human* to understand, as opposed to cyclomatic complexity, which measures
the number of independent paths (a testability metric). See
[cognitive-complexity-of-code.md](cognitive-complexity-of-code.md) for the full
synthesis. The metric awards points for three things:

- **Structural increments** — each control-flow break (`if`, `for`, `while`,
  `except`, `match`, ternary, a boolean-operator sequence, …) costs points.
- **Nesting increments** — a control-flow break that sits *inside* other breaks
  costs *extra*, proportional to how deeply nested it is. This is the part that
  models "I have to hold all the enclosing conditions in my head."
- **A few fundamental increments** — e.g. recursion.

cococo implements this per function. The entry point
`get_cognitive_complexity_breakdown(funcdef)` walks the function body and emits
one `Contribution` per scored construct; the score is the sum of their points.
The walk tracks a running `nesting_level` (`increment_by`) that goes up by one
each time it descends into a nesting construct.

The relevant detail for this spec: **a nested function definition is currently
treated as a nesting construct.** In
`cognitive_complexity/utils/ast.py::process_node_itself`,
`FunctionDef`/`AsyncFunctionDef`/`Lambda` are all "incrementers": entering one
adds a nesting level and the walk recurses into its body. So the inner
function's control flow is summed into the enclosing function, at `+1` nesting
per level of function containment.

### The one existing exception: `is_decorator`

`cognitive_complexity/utils/ast.py::is_decorator` already treats folding as wrong
for one specific shape — a function that *defines a single inner function and
returns it by name*:

```python
def deco(f):
    def wrapper(*a, **k):
        ...
    return wrapper
```

For this shape, `get_cognitive_complexity_breakdown` scores the function *by its
inner function* instead of folding (it recurses straight into `body[0]`). The
code comment notes that "a decorator and a value-returning closure factory are
structurally identical." This is the project already agreeing, in code, that
folding misrepresents a wrapper. The defect below is that this agreement only
covers the **N = 1** case.

---

## 2. The problem

### 2.1 Reproduction (measured on 1.5.0)

A factory whose outer function is trivial — it defines two independent handlers
and returns them:

```python
def make_handlers():
    def handler_a(x):
        if x > 0:
            for i in range(x):
                if i % 2:
                    print(i)
        return x
    def handler_b(x):
        if x < 0:
            while x:
                x += 1
        return x
    return [handler_a, handler_b]
```

Reproduction: save the factory above as `repro_nested.py` and, with
`cococo 1.5.0`, run `cococo repro_nested.py --min 0` (or `cococo --explain
repro_nested.py::make_handlers` for the per-construct breakdown). Then run the
same command on a copy where `handler_a`/`handler_b` are pasted at module level
to get the standalone scores. Measured:

| measured                          | score |
| --------------------------------- | ----: |
| `make_handlers` (folded, today)   |    14 |
| `handler_a` alone (at top level)  |     6 |
| `handler_b` alone (at top level)  |     3 |

The outer function's own control flow is ~0 (define, define, return), yet it
scores **14**. Two things are wrong:

1. **Misattribution.** One number (14) stands for two unrelated units. It does
   not describe `make_handlers`, and it does not tell you `handler_a` is the hard
   one.
2. **Nesting surcharge.** `14 > 6 + 3 = 9`. Folding doesn't just aggregate; it
   *inflates*. Each construct inside a handler pays an extra nesting point for
   living one `def` deeper than it would at top level. So the folded total isn't
   even a meaningful sum — it's a sum plus a containment tax.

### 2.2 Why it matters in practice

Factory/registry shapes are everywhere: FastAPI/Flask `create_app`, Click
command groups, pytest fixtures defining inner helpers, decorator factories,
dispatch tables of closures.

The originating audit report (against `cococo 1.5.0`) measured a FastAPI
`create_app` at **1037** — **1** of it the function's own control flow, **1036**
from 96 unrelated route handlers folded in and surcharged. That figure is from a
private codebase and is **not reproduced here**; treat it as motivating anecdote,
not a citable benchmark. The reproducible stand-in is the §2.1 repro, verified on
`cococo 1.5.0`: `make_handlers` = 14 versus `handler_a` = 6 + `handler_b` = 3.
§5.5 reproduces the `create_app` shape itself in a few lines, with measured
before/after numbers (folded 11 → per-unit 0 + 6 + 1).

As a CI gate signal the create_app number is useless: it can never approach a
sane threshold without dismantling the factory, and it names the wrong thing — it
tells you nothing about *which* handler is hard to read.

### 2.3 Is folding "wrong" per the spec?

Not strictly. Campbell's white paper does increment nesting for "nested methods
(and method-like structures such as lambdas)," so a literal recursive reading
folds. But the metric's *stated purpose* is to score how hard a **unit** is to
understand, and the tools that apply it (including SonarQube) surface findings
**per function/method**. A factory's handlers are independent units; collapsing
them into one number defeats the purpose, and — via the surcharge — isn't even a
faithful aggregate. cococo's own `is_decorator` special case is the existing
admission that per-unit is the right granularity. This spec generalizes that
admission from N = 1 to all N.

---

## 3. Options considered

### Option A — score named nested functions as their own units (proposed)

Recurse into `FunctionDef`/`AsyncFunctionDef` as **separate analysis targets**,
report them with a qualified name (e.g. `make_handlers.<locals>.handler_a`), and
do **not** fold their complexity into the parent. Keep folding **lambdas** —
they are anonymous, have no independent identity, and match the spec's
"method-like structures such as lambdas."

Effect on the repro: `make_handlers` → ~0, `handler_a` → 6, `handler_b` → 3,
each reported on its own row. The surcharge disappears because each unit is
scored from nesting level 0.

### Option B — generalize `is_decorator` into `is_factory`

Don't fold when the outer body is *predominantly* nested function definitions.

Rejected: it replaces a clean rule with a fuzzy threshold ("predominantly"),
keeps two scoring code paths, and still leaves the nesting surcharge in place for
the cases it chooses to keep folding (an ordinary function with one inline helper
that contains a loop still over-counts). A partial fix with a judgment call baked
into the metric.

### Option C — expose an `own`/`folded` split and an opt-out flag

Keep folding as the default, but add an `own` (intrinsic) number beside the
`total`, plus a `--no-fold-nested` flag.

Rejected as the primary fix: it only addresses misattribution (#1), not the
surcharge (#2) — the `folded` number remains the inflated aggregate. It is also
**degenerate under Option A**: once nested units are reported on their own rows,
a parent's "folded" portion has been redistributed into those rows, so there is
nothing left to put in a `folded` column (`own == total` for every unit). You
want A *or* C's model, not both.

---

## 4. Decision

**Adopt Option A as the default.** It is the only option that fixes both the
misattribution and the surcharge; it matches how the metric is applied in
practice (per unit); and it is *less* code than the status quo because it
subsumes the `is_decorator` special case into one uniform rule.

---

## 5. Detailed design

Three changes, all small:

### 5.1 Stop folding named defs into the parent score

In `cognitive_complexity/api.py::_collect_breakdown`, a nested
`FunctionDef`/`AsyncFunctionDef` becomes a no-op leaf: it contributes nothing to
the enclosing function and the walk does not recurse into it. Correspondingly,
remove `FunctionDef`/`AsyncFunctionDef` from the incrementer set in
`cognitive_complexity/utils/ast.py::process_node_itself`. **`Lambda` stays** an
incrementer (folds, adds a nesting level, recurses).

The now-unreachable `"nested-func"` label in `describe_node` is removed.

### 5.2 Report each named nested def as its own unit

In `cognitive_complexity/cli.py::_collect`, flip the `inside_func` guard. Today
it *prevents* descending into a function (so nested defs are never reported);
under A, descend and append each named nested def as its own
`(funcdef, qualname)`, then keep recursing for deeper nesting.

`_collect` threads an enclosing-name **prefix** (a scope stack) through its
recursion, exactly as it already does for the class qualifier today: entering a
`ClassDef` extends the prefix with `Klass.` (current behavior, unchanged);
entering a named def appends `.<locals>.<name>` to the current prefix before
recursing into that def's body. The composed qualnames are:

- top-level function → `do_thing`
- method → `Klass.method` (unchanged)
- nested function → `outer.<locals>.inner`
- method-local function → `Klass.method.<locals>.inner`

The key contract: the prefix is passed *down* the recursion, so a def nested
inside a method keeps the full `Klass.method.` prefix rather than dropping the
class.

### 5.3 Delete `is_decorator`

With nested units reported on their own rows, the decorator/closure-factory case
is no longer special: `deco` shows its own score (~0) and
`deco.<locals>.wrapper` shows the real complexity. Remove `is_decorator` (and its
helper `_returns_name`) and the early-return branch in
`get_cognitive_complexity_breakdown`. One uniform rule replaces a
structural-pattern heuristic.

### 5.4 Worked example

The current `tests/test_cognitive_complexity.py::test_nested_functions` pins the
old behavior:

```python
def f(a):
    def foo(a):
        if a:      # +2 today: 1 structural + 1 nesting (inside foo, inside f)
            return 1
    bar = lambda a: lambda b: b or 2   # +1 (the `or`; lambdas still fold)
    return bar(foo(a))(a)
# f == 3 today
```

Under Option A:

- `f` → **1** (only the lambda's `b or 2`; the named `foo` no longer folds in)
- `f.<locals>.foo` → **1**, reported as its own unit (the `if a` is now scored
  from nesting 0, so `+1`, not `+2`)

The missing point between old `f == 3` and new `f == 1` + `foo == 1` is exactly
the nesting surcharge being removed.

### 5.5 Worked example: a reproducible mini app-factory

The 1037 figure in §2.2 is from a private codebase, but the *shape* reproduces in
a few lines. The decorators stand in for `@app.route`/`@app.get`; they don't add
score, and the handlers are the real units:

```python
def create_app():
    app = FastAPI()

    @app.get("/a")
    def handler_a(x):
        if x > 0:
            for i in range(x):
                if i % 2:
                    log(i)
        return x

    @app.get("/b")
    def handler_b(x):
        if x < 0:
            return -x
        return x

    return app
```

Measured on `cococo 1.5.0` (`cococo repro_app.py --min 0`, then the handlers
scored at top level):

| measured                         | score |
| -------------------------------- | ----: |
| `create_app` (folded, today)     |    11 |
| `handler_a` alone                |     6 |
| `handler_b` alone                |     1 |

Under Option A: `create_app` → **0** (own: assign, two defs, return), with
`create_app.<locals>.handler_a` → **6** and `create_app.<locals>.handler_b` →
**1** on their own rows. Aggregate `0 + 6 + 1 = 7` versus the folded `11`; the
removed surcharge is `4` (three constructs in `handler_a` each shed one
containment level, one in `handler_b`). This is the 1037 case in miniature, fully
reproducible.

---

## 6. Semantics, edge cases, and trade-offs

- **Lambdas still fold.** Anonymous, no identity, spec-aligned. A heavy
  `key=lambda ...` ternary chain still counts against its enclosing function.
- **Name collisions.** Two nested functions with the same name in different
  branches produce the same qualname. The real key in the report is
  `path:lineno`, which is unique; `--explain file.py:LINE` selects precisely,
  while a qualname match returns the first hit. Acceptable.
- **Recursion** is detected per unit, unchanged. Direct recursion of a nested
  function is scored within that nested unit.
- **Decorators on nested defs** (e.g. `@app.route` on each handler) don't add
  score themselves; each decorated handler is reported as its own unit — exactly
  the FastAPI case.
- **The one genuine trade-off.** A function that defines many *trivial* closures
  (say 20 closures each scoring 3, under a threshold of 5) will show 20 small
  rows, none flagged — where folding would have flagged the parent at ~60. That
  is a *size* signal (function length / number of locals), not cognitive
  complexity in Campbell's sense, and catching it belongs to a different lint.
  Stated here so it is a deliberate choice, not a surprise.
- **The refactor-suggestion engine** (`cognitive_complexity/refactor.py`) already
  skips nested defs when finding regions, so it is consistent with A and needs no
  change. Its reported *score*, sourced from the breakdown, simply becomes the
  per-unit number.

---

## 7. Migration and compatibility

This is a **breaking change to reported numbers** → ship as `2.0.0`.

- **Scores drop** for factory/closure-heavy functions, and **new rows appear**
  for named nested functions. CI gates that encoded folded totals will change
  (mostly in the user's favor: trivial factories stop failing; genuinely-complex
  handlers start being named individually).
- **README:** the line *"nested functions are folded into their enclosing
  function's score"* inverts; document the per-unit model and the qualname
  format.
- **Self-dogfood unaffected:** cococo's own package has no nested `def`s, so
  `just complexity --max 10` is unchanged.
- **Downstream consumer (sequenced):** the parent `data_pipeline` depends on
  `cognitive-complexity`. Before tagging 2.0.0, in order:
  1. Grep its CI/config for pinned cognitive-complexity thresholds (e.g.
     `--max`, `cococo`/complexity gate recipes in justfiles or workflows).
  2. If any exist, land a PR *there first* that raises or removes them. That PR
     must be **merged to `data_pipeline`'s main branch** — not merely open —
     before cococo 2.0.0 is tagged. If review drags, delay the cococo release
     rather than ship ahead of the consumer fix; an open-but-unmerged PR will not
     stop the dependent's next scheduled dependency bump from going red.
  3. If none exist, record "no downstream gates pinned (checked `<commit>`)"
     in the 2.0.0 release notes so the check is auditable.

### Open question: transitional flag?

Default recommendation is a **clean break** at 2.0 with no dual model (one
scoring path is simpler to maintain and reason about). If a staged migration is
needed, a temporary `--fold-nested` flag could preserve 1.x numbers for one
release before removal — at the cost of carrying two scoring models meanwhile.

---

## 8. Test plan

Test-first: write the new per-unit assertions (they fail against today's
folding), then make the §5 changes.

- **Flip existing pins** (~8 cases): `test_nested_functions`; the decorator tests
  in `tests/test_cognitive_complexity.py` (`test_a_decorator_complexity`,
  `test_not_a_decorator_complexity`, `test_decorator_generator_complexity`);
  `test_decorator_is_scored_by_inner_function` and
  `test_closure_factory_is_indistinguishable_from_decorator` in
  `tests/test_edge_cases.py`; and the decorator/`--explain` cases in
  `tests/test_explain.py`. Rewrite to assert the new numbers and that nested
  defs appear as their own rows.
- **New fixtures:** an app-factory (N nested defs + `return app`) → outer ≈ 0,
  each handler on its own row at its standalone score; a function with one inline
  helper; deeply nested closures (qualname composition); a lambda-heavy function
  (assert lambdas still fold).
- **Discovery:** assert `discovery.scored_functions` now returns nested units
  with composed qualnames, and that `--explain outer.<locals>.inner` and
  `--explain file.py:LINE` both resolve them.
- **Property (two independently checkable invariants, not a residual equation).**
  Defining the surcharge as `old − new` would make any equality tautological, so
  assert instead, for any function subtree: (a) `new_aggregate <=
  old_folded_total` (re-leveling can only *remove* nesting points, never add);
  and (b) the **multiset of scored construct types is identical** old vs new —
  the same `if`/`for`/`bool-op`/… constructs are counted, only their nesting
  level and which unit they're attributed to change. Invariant (b) is the one
  that actually catches an attribution bug: a construct dropped, double-counted,
  or wrongly re-leveled breaks it, whereas a residual-surcharge equation would
  silently absorb the error.
- Maintain the 100% coverage floor.

---

## 9. Summary of file changes

| file | change |
| ---- | ------ |
| `cognitive_complexity/api.py` | nested named defs are no-op leaves; remove `is_decorator` branch |
| `cognitive_complexity/utils/ast.py` | drop `FunctionDef`/`AsyncFunctionDef` from incrementers; remove `is_decorator`, `_returns_name`, `"nested-func"` label |
| `cognitive_complexity/cli.py` | `_collect` descends into and reports nested defs with composed qualnames |
| `tests/` | flip ~8 pinned cases; add factory/closure/lambda fixtures |
| `README.md` | invert the folding note; document per-unit model + qualname format |
| `cognitive_complexity/__init__.py` | bump to `2.0.0` |
