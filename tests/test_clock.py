import unittest
from datetime import datetime, timedelta, timezone

from ca.clock import FakeClock, IST, is_quiet, local_now, next_quiet_end, tzinfo_for


class TimezoneTests(unittest.TestCase):
    def test_known_names(self):
        self.assertEqual(tzinfo_for("Asia/Kolkata"), IST)
        self.assertEqual(tzinfo_for("UTC"), timezone.utc)
        self.assertEqual(tzinfo_for("UTC+05:30").utcoffset(None), timedelta(hours=5, minutes=30))
        self.assertEqual(tzinfo_for("UTC-08:00").utcoffset(None), timedelta(hours=-8))

    def test_unknown_name_is_an_error_without_leaking_input(self):
        with self.assertRaises(ValueError):
            tzinfo_for("Nowhere/Land")

    def test_local_now_converts(self):
        clock = FakeClock(datetime(2026, 11, 13, 18, 30, tzinfo=timezone.utc))
        local = local_now(clock, "Asia/Kolkata")
        self.assertEqual((local.day, local.hour, local.minute), (14, 0, 0))   # next day, midnight IST


class FakeClockTests(unittest.TestCase):
    def test_advance_and_set(self):
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
        clock.advance(hours=25)
        self.assertEqual(clock.now(), datetime(2026, 1, 2, 1, tzinfo=timezone.utc))
        clock.set(datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(clock.now().year, 2027)

    def test_naive_datetime_is_refused(self):
        with self.assertRaises(ValueError):
            FakeClock(datetime(2026, 1, 1))


def at(hour, minute=0):
    return datetime(2026, 11, 13, hour, minute, tzinfo=IST)


class QuietHoursTests(unittest.TestCase):
    def test_crossing_midnight(self):
        self.assertTrue(is_quiet(at(23, 30), 23, 7))
        self.assertTrue(is_quiet(at(3), 23, 7))
        self.assertFalse(is_quiet(at(7), 23, 7))      # end is exclusive
        self.assertFalse(is_quiet(at(22, 59), 23, 7))
        self.assertTrue(is_quiet(at(23), 23, 7))      # start is inclusive

    def test_same_day_range_and_empty_range(self):
        self.assertTrue(is_quiet(at(2), 1, 5))
        self.assertFalse(is_quiet(at(5), 1, 5))
        self.assertFalse(is_quiet(at(12), 6, 6))

    def test_next_quiet_end(self):
        late = datetime(2026, 11, 13, 23, 30, tzinfo=IST)
        self.assertEqual(next_quiet_end(late, 23, 7), datetime(2026, 11, 14, 7, 0, tzinfo=IST))
        early = datetime(2026, 11, 14, 3, 0, tzinfo=IST)
        self.assertEqual(next_quiet_end(early, 23, 7), datetime(2026, 11, 14, 7, 0, tzinfo=IST))
        noon = datetime(2026, 11, 14, 12, 0, tzinfo=IST)
        self.assertEqual(next_quiet_end(noon, 23, 7), noon)


if __name__ == "__main__":
    unittest.main()
