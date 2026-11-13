import unittest

from radar import filters, skills
from radar.run import analyse, share


class SkillTests(unittest.TestCase):
    def test_counts_once_and_handles_punctuation(self):
        found = skills.find_skills("We use Python, C++ and React.js. Python again.")
        self.assertTrue({"Python", "C++", "React"} <= found)

    def test_java_is_not_javascript(self):
        self.assertIn("Java", skills.find_skills("Strong Java skills"))
        self.assertNotIn("Java", skills.find_skills("Strong JavaScript skills"))

    def test_c_alone_matches_but_not_inside_words(self):
        self.assertIn("C", skills.find_skills("Proficient in C/C++"))
        self.assertNotIn("C", skills.find_skills("Plan for CI and CD"))

    def test_ros_is_not_across(self):
        self.assertIn("ROS", skills.find_skills("Experience with ROS2 and Gazebo"))
        self.assertNotIn("ROS", skills.find_skills("across the company"))

    def test_clean_text_unescapes_double_escaped_html(self):
        self.assertEqual(skills.clean_text("&lt;p&gt;Hello&amp;nbsp;world&lt;/p&gt;").split()[0], "Hello")


class FilterTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(filters.level_of("Software Engineering Intern"), "intern")
        self.assertEqual(filters.level_of("Senior Software Engineer"), "senior")
        self.assertEqual(filters.level_of("Associate Software Engineer"), "entry")
        self.assertEqual(filters.level_of("Software Engineer"), "mid")

    def test_location_and_role(self):
        self.assertTrue(filters.in_india("Bengaluru, Karnataka"))
        self.assertFalse(filters.in_india("Austin, TX"))
        self.assertTrue(filters.is_tech("ML Engineer"))
        self.assertFalse(filters.is_tech("Sales Engineer Recruiter"))


class AnalyseTests(unittest.TestCase):
    def test_only_india_tech_kept_and_share(self):
        postings = [
            {"company": "a", "title": "Software Engineer", "location": "Bengaluru", "url": "", "text": "Python and Docker"},
            {"company": "b", "title": "Software Engineer", "location": "Austin", "url": "", "text": "Python"},
            {"company": "c", "title": "Account Executive", "location": "Bengaluru", "url": "", "text": "Python"},
        ]
        rows = analyse(postings, [])
        self.assertEqual(len(rows), 1)
        n, counts = share(rows, lambda r: True)
        self.assertEqual((n, counts["Python"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
