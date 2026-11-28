"""The console operator's prompts (no terminal: every manual step is skipped, never a crash)."""

from tbbench.prompts import ConsoleOperator


def feeder(*answers):
    it = iter(answers)

    def inp(_prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None
    return inp


def test_confirm_and_skip():
    op = ConsoleOperator(feeder("", "s", "no"), out=lambda *_: None)
    assert op.confirm("k", "do it") is True
    assert op.confirm("k", "do it") is False and op.confirm("k", "do it") is False
    assert op.confirm("k", "stdin closed") is False


def test_measure():
    said = []
    op = ConsoleOperator(feeder("abc", "1.25", ""), out=said.append)
    assert op.measure("k", "current", "mA") == 1.25 and said == ["    not a number: 'abc'"]
    assert op.measure("k", "current", "mA") is None
    assert op.measure("k", "stdin closed", "mA") is None
