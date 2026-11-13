import unittest

from ca.router import parse


class MenuWordTests(unittest.TestCase):
    def test_menu_words_any_case_and_punctuation(self):
        for w in ("today", "TODAY", " Week ", "apps!", "Inbox?", "pause", "resume", "undo", "help", "focus"):
            self.assertEqual(parse(w).kind, w.strip(" !?").lower())

    def test_empty(self):
        self.assertEqual(parse("").kind, "empty")
        self.assertEqual(parse("   ").kind, "empty")
        self.assertEqual(parse(None).kind, "empty")


class ReplyTests(unittest.TestCase):
    def test_yes_skip_later_with_numbers(self):
        c = parse("yes 3")
        self.assertEqual((c.kind, c.number), ("yes", 3))
        self.assertEqual(parse("Y #12").number, 12)
        self.assertEqual(parse("skip 2").kind, "skip")
        self.assertEqual(parse("no 4").kind, "skip")
        self.assertEqual(parse("later 5").kind, "later")
        self.assertEqual(parse("ok 1").kind, "yes")

    def test_yes_without_number(self):
        c = parse("yes")
        self.assertEqual((c.kind, c.number), ("yes", None))

    def test_edit_keeps_text(self):
        c = parse("edit 2 make it shorter please")
        self.assertEqual((c.kind, c.number, c.text), ("edit", 2, "make it shorter please"))

    def test_edit_without_number_is_free_text(self):
        self.assertEqual(parse("edit this please").kind, "free_text")


class PlanCommandTests(unittest.TestCase):
    def test_push(self):
        c = parse("push DSA to tomorrow")
        self.assertEqual((c.kind, c.args), ("push", {"task": "DSA", "to": "tomorrow"}))
        self.assertEqual(parse("Push ML videos until Saturday").args["to"], "saturday")

    def test_done_and_skip_task(self):
        self.assertEqual(parse("done leetcode").args["task"], "leetcode")
        self.assertEqual(parse("skip gate today").kind, "skip_task")
        self.assertEqual(parse("skip 2").kind, "skip")          # a number means an approval, not a task

    def test_free_hours(self):
        for text, hours in (("3 hours", 3.0), ("only 2 hours free", 2.0), ("I have 4 hrs", 4.0), ("free 1.5 hours", 1.5)):
            c = parse(text)
            self.assertEqual((c.kind, c.args["hours"]), ("free", hours))

    def test_free_text_fallback(self):
        c = parse("I am travelling tomorrow and cannot study")
        self.assertEqual((c.kind, c.text), ("free_text", "I am travelling tomorrow and cannot study"))


if __name__ == "__main__":
    unittest.main()
