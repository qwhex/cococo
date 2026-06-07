from conftest import get_code_snippet_complexity


def test_simple_if_simple_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a:  # +1
            return 1
    """)
        == 1
    )


def test_simple_if_simple_condition_complexity_with_print():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a:  # +1
            print('1')
    """)
        == 1
    )


def test_simple_if_serial_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a and b and True:  # +2
            return 1
    """)
        == 2
    )


def test_simple_if_serial_heterogenious_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a and b or True:  # +3
            return 1
    """)
        == 3
    )


def test_simple_if_complex_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if (  # +1
            a and b and  # +1
            (c or d)  # +1
        ):
            return 1
    """)
        == 3
    )


def test_simple_structure_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if (a):  # +1
            return 1
        if (b):  # +1
            return 2
    """)
        == 2
    )


def test_simple_elif_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if (a):  # +1
            return 1
        elif (b):  # +1
            return 2
        else:  # +1
            return 3
    """)
        == 3
    )


def test_simple_else_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a):
        if (a):  # +1
            return 1
        else:  # +1
            return 3
    """)
        == 2
    )


def test_nested_structure_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a:  # +1
            for i in range(b):  # +2
                return 1
    """)
        == 3
    )


def test_very_nested_structure_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a:  # +1
            for i in range(b):  # +2
                if b:  # +3
                    return 1
    """)
        == 6
    )


def test_try_condition_complexity_simple():
    assert (
        get_code_snippet_complexity("""
    def f():
        try:
            print('hello1')
        except Exception:  # +1
            print('goodbye')
    """)
        == 1
    )


def test_try_condition_complexity_with_multiple_lines():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        try:
            print('hello1')
            print('hello2')
            print('hello3')
            print('hello4')
            print('hello5')
        except Exception:  # +1
            print('goodbye')
    """)
        == 1
    )


def test_try_condition_complexity_with_nesting():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        try:
            for foo in bar:  # +1
                if a > 0:  # +2
                    return a
        except Exception:  # +1
            if a < 0:  # +2
                return a
    """)
        == 6
    )


def test_recursion_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a):
        return a * f(a - 1)  # +1 for recursion
    """)
        == 1
    )


def test_real_function():
    assert (
        get_code_snippet_complexity("""
    def process_raw_constant(constant, min_word_length):
        processed_words = []
        raw_camelcase_words = []
        for raw_word in re.findall(r'[a-z]+', constant):  # +1
            word = raw_word.strip()
            if (  # +2 (nesting = 1)
                len(word) >= min_word_length  # +2 (2 bool operator sequences)
                and not (word.startswith('-') or word.endswith('-'))
            ):
                if is_camel_case_word(word):  # +3 (nesting=2)
                    raw_camelcase_words.append(word)
                else:  # +1
                    processed_words.append(word.lower())
        return processed_words, raw_camelcase_words
    """)
        == 9
    )


def test_real_function_with_try():
    assert (
        get_code_snippet_complexity("""
    def process_raw_constant(constant, min_word_length):
        try:
            processed_words = []
            raw_camelcase_words = []
            for raw_word in re.findall(r'[a-z]+', constant):  # +1
                word = raw_word.strip()
                if (  # +2 (nesting = 1)
                    len(word) >= min_word_length  # +2 (2 bool operator sequences)
                    and not (word.startswith('-') or word.endswith('-'))
                ):
                    if is_camel_case_word(word):  # +3 (nesting=2)
                        raw_camelcase_words.append(word)
                    else:  # +1
                        processed_words.append(word.lower())
            return processed_words, raw_camelcase_words
        except Exception as exp:  # +1
            return 1
    """)
        == 9 + 1
    )


def test_break_and_continue():
    assert (
        get_code_snippet_complexity("""
    def f(a):
        for a in range(10):  # +1
            if a % 2:  # +2
                continue
            if a == 8:  # +2
                break
    """)
        == 5
    )


def test_nested_functions():
    # Named nested defs are scored as their own units, not folded into `f`. So
    # `f`'s own score is just the lambda's `b or 2` bool-op (+1); the `if a`
    # inside `foo` belongs to `foo`, not `f`. (Lambdas still fold.)
    assert (
        get_code_snippet_complexity("""
    def f(a):
        def foo(a):
            if a:  # belongs to foo, not f
                return 1
        bar = lambda a: lambda b: b or 2  # +1 (lambdas fold)
        return bar(foo(a))(a)
    """)
        == 1
    )


def test_ternary_operator():
    assert (
        get_code_snippet_complexity("""
    def f(a):
        if a % 2:  # +1
            return 'c' if a else 'd'  # +2
        return 'a' if a else 'b'  # +1
    """)
        == 4
    )


def test_nested_if_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a == b:  # +1
            if (a):  # +2 (nesting=1)
                return 1
        return 0
    """)
        == 3
    )


def test_nested_else_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a == b:  # +1
            if (a):  # +2 (nesting=1)
                return 1
            else:  # +1
                return 3
        return 0
    """)
        == 4
    )


def test_nested_elif_condition_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a, b):
        if a == b:  # +1
            if (a):  # +2 (nesting=1)
                return 1
            elif (b):  # +1
                return 2
            else:  # +1
                return 3
        return 0
    """)
        == 5
    )


def test_for_else_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a):
        for a in range(10):  # +1
            if a % 2:  # +2
                continue
            if a == 8:  # +2
                break
        else:  # +1
            return 5
    """)
        == 6
    )


def test_while_else_complexity():
    assert (
        get_code_snippet_complexity("""
    def f(a):
        a = 0
        while a < 10:  # +1
            if a % 2:  # +2
                continue
            if a == 8:  # +2
                break
            a += 1
        else:  # +1
            return 5
    """)
        == 6
    )


def test_decorator_factory_own_score_excludes_inner():
    # A decorator factory's own body is just "define inner, return inner", so its
    # own score is 0. The `if condition` belongs to `inner`, scored as its own
    # unit (see tests/test_cli.py for the per-unit reporting).
    assert (
        get_code_snippet_complexity("""
    def a_decorator(a, b):
        def inner(func):
            if condition:  # belongs to inner, not a_decorator
                print(b)
            func()
        return inner
    """)
        == 0
    )


def test_function_with_an_inline_helper_excludes_the_helper():
    # The helper `inner` is a separate unit; the enclosing function's own score
    # excludes it (here: 0, just an assignment and a return).
    assert (
        get_code_snippet_complexity("""
    def not_a_decorator(a, b):
        my_var = a*b
        def inner(func):
            if condition:  # belongs to inner
                print(b)
            func()
        return inner
    """)
        == 0
    )


def test_deeply_nested_factory_own_score_is_zero():
    # Each named def is its own unit; the outer factory only defines and returns.
    assert (
        get_code_snippet_complexity("""
    def decorator_generator(a):
        def generator(func):
            def decorator(func):
                if condition:  # belongs to the innermost decorator
                    print(b)
                return func()
            return decorator
        return generator
    """)
        == 0
    )
