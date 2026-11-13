import json
import unittest

from ca import approvals, db
from ca.approvals import ApprovalError, Executors


def setup():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    calls = []
    ex = Executors(
        run={"email": lambda p: calls.append(("run", p)) or "sent"},
        undo={"email": lambda p: calls.append(("undo", p)) or "recalled"},
    )
    return conn, ex, calls


class ApproveTests(unittest.TestCase):
    def test_approve_runs_executor_once(self):
        conn, ex, calls = setup()
        a = approvals.create(conn, "email", "Email Prof X", {"to": "x@example.org"})
        self.assertEqual(approvals.approve(conn, a, ex), "sent")
        self.assertEqual(len(calls), 1)
        with self.assertRaises(ApprovalError):          # cannot approve twice
            approvals.approve(conn, a, ex)
        self.assertEqual(len(calls), 1)

    def test_nothing_runs_while_paused(self):
        conn, ex, calls = setup()
        a = approvals.create(conn, "email", "s")
        db.set_paused(conn, True)
        with self.assertRaises(ApprovalError):
            approvals.approve(conn, a, ex)
        self.assertEqual(calls, [])
        self.assertEqual(approvals.get(conn, a)["status"], "pending")
        db.set_paused(conn, False)
        approvals.approve(conn, a, ex)
        self.assertEqual(len(calls), 1)

    def test_unknown_kind_and_missing_item(self):
        conn, ex, _ = setup()
        a = approvals.create(conn, "mystery", "s")
        with self.assertRaises(ApprovalError):
            approvals.approve(conn, a, ex)
        self.assertEqual(approvals.get(conn, a)["status"], "pending")
        with self.assertRaises(ApprovalError):
            approvals.approve(conn, 999, ex)

    def test_failing_executor_leaves_it_pending_and_hides_internals(self):
        conn, _, _ = setup()
        boom = Executors(run={"email": lambda p: (_ for _ in ()).throw(RuntimeError("secret detail"))})
        a = approvals.create(conn, "email", "s")
        with self.assertRaises(ApprovalError) as ctx:
            approvals.approve(conn, a, boom)
        self.assertNotIn("secret detail", str(ctx.exception))
        self.assertEqual(approvals.get(conn, a)["status"], "pending")


class OtherActionTests(unittest.TestCase):
    def test_reject_later_edit(self):
        conn, ex, calls = setup()
        a = approvals.create(conn, "email", "Email Prof X", {"body": "hi"})
        approvals.later(conn, a)
        self.assertEqual(approvals.get(conn, a)["status"], "pending")
        approvals.edit(conn, a, "shorter hi")
        row = approvals.get(conn, a)
        self.assertEqual(json.loads(row["payload"])["edited_text"], "shorter hi")
        self.assertTrue(row["summary"].endswith("(edited)"))
        approvals.edit(conn, a, "even shorter")
        self.assertEqual(approvals.get(conn, a)["summary"].count("(edited)"), 1)
        approvals.reject(conn, a)
        self.assertEqual(approvals.get(conn, a)["status"], "rejected")
        with self.assertRaises(ApprovalError):
            approvals.edit(conn, a, "too late")

    def test_undo_only_after_approval_and_runs_undoer(self):
        conn, ex, calls = setup()
        a = approvals.create(conn, "email", "s")
        with self.assertRaises(ApprovalError):
            approvals.undo(conn, a, ex)
        approvals.approve(conn, a, ex)
        self.assertEqual(approvals.last_approved(conn)["id"], a)
        self.assertEqual(approvals.undo(conn, a, ex), "recalled")
        self.assertEqual(approvals.get(conn, a)["status"], "undone")
        self.assertIsNone(approvals.last_approved(conn))

    def test_pending_list(self):
        conn, ex, _ = setup()
        a = approvals.create(conn, "email", "one")
        b = approvals.create(conn, "email", "two")
        approvals.approve(conn, a, ex)
        self.assertEqual([r["id"] for r in approvals.pending(conn)], [b])


if __name__ == "__main__":
    unittest.main()
