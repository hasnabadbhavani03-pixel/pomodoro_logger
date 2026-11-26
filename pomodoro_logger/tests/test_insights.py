import unittest
from datetime import date
from pomodoro.models import Session
from pomodoro.insights import build_insights

class InsightsTests(unittest.TestCase):
    def test_empty_data(self):
        self.assertEqual(build_insights([])[0]['kind'], 'welcome')
    def test_subject_and_recent_and_coverage(self):
        sessions=[Session(1,'2026-11-26','Math',50,2,5,'',''),
                  Session(2,'2026-11-10','History',25,1,5,'','')]
        result=build_insights(sessions,date(2026,11,26))
        kinds={x['kind'] for x in result}
        self.assertIn('subject',kinds); self.assertIn('recent',kinds); self.assertIn('coverage',kinds)
    def test_future_sessions_not_recent(self):
        sessions=[Session(1,'2026-11-30','Math',50,2,5,'','')]
        self.assertNotIn('recent',{x['kind'] for x in build_insights(sessions,date(2026,11,26))})
if __name__=='__main__': unittest.main()
