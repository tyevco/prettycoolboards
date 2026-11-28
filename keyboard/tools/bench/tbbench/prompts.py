"""The person at the bench: prompts for the steps a program cannot do (press NRST, plug a host in, read a meter).

ConsoleOperator asks on the terminal; ScriptedOperator answers from a table (the tests, and the simulators' hooks);
NullOperator answers nothing, so every manual step is recorded as skipped.
"""

from __future__ import annotations


class Operator:
    interactive = False

    def confirm(self, key, text):
        """Ask the operator to do something; True once done, False if they skip it."""
        return False

    def measure(self, key, text, unit):
        """Ask for a reading from an instrument; a float, or None if skipped."""
        return None

    def ask(self, key, text):
        """A yes/no question about what the operator saw; True, False, or None if skipped."""
        return None

    def say(self, text):
        pass


class NullOperator(Operator):
    def __init__(self):
        self.asked = []

    def confirm(self, key, text):
        self.asked.append(("confirm", key, text))
        return False

    def measure(self, key, text, unit):
        self.asked.append(("measure", key, text))
        return None

    def ask(self, key, text):
        self.asked.append(("ask", key, text))
        return None


class ConsoleOperator(Operator):
    interactive = True

    def __init__(self, inp=input, out=print):
        self.inp, self.out = inp, out

    def _ask(self, prompt):
        try:
            return self.inp(prompt).strip()
        except EOFError:            # no terminal (stdin closed): every manual step is skipped
            return "s"

    def confirm(self, key, text):
        a = self._ask(f"\n>>> {text}\n    Enter when done, 's' to skip: ").lower()
        return a not in ("s", "skip", "n", "no")

    def measure(self, key, text, unit):
        while True:
            a = self._ask(f"\n>>> {text} [{unit}] (blank to skip): ")
            if a == "s":
                return None
            if not a:
                return None
            try:
                return float(a)
            except ValueError:
                self.out(f"    not a number: {a!r}")

    def ask(self, key, text):
        while True:
            a = self._ask(f"\n>>> {text}\n    y / n, 's' to skip: ").lower()
            if a in ("y", "yes"):
                return True
            if a in ("n", "no"):
                return False
            if a in ("s", "skip"):
                return None
            self.out(f"    y, n or s: {a!r}")

    def say(self, text):
        self.out(text)


class ScriptedOperator(Operator):
    """answers: key -> a value, or a callable(key, text) returning one. Unknown keys are skipped."""

    def __init__(self, answers=None):
        self.answers = dict(answers or {})
        self.asked = []
        self.said = []

    def _answer(self, kind, key, text):
        self.asked.append((kind, key, text))
        a = self.answers.get(key)
        return a(key, text) if callable(a) else a

    def confirm(self, key, text):
        return bool(self._answer("confirm", key, text))

    def measure(self, key, text, unit):
        a = self._answer("measure", key, text)
        return None if a is None else float(a)

    def ask(self, key, text):
        a = self._answer("ask", key, text)
        return None if a is None else bool(a)

    def say(self, text):
        self.said.append(text)
