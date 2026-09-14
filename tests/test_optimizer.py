import unittest
from src.optimizer.transfers import TransferOptimizer

class TestOptimizer(unittest.TestCase):

    def setUp(self):
        squad = [
            {"id": 1, "position": "MID", "price": 7.0, "expected_points": 4.0},
            {"id": 2, "position": "FWD", "price": 8.0, "expected_points": 5.0},
        ]
        players = [
            {"id": 3, "position": "MID", "price": 7.0, "expected_points": 7.0},
            {"id": 4, "position": "FWD", "price": 8.0, "expected_points": 6.0},
        ]
        self.optimizer = TransferOptimizer(squad, players, free_transfers=1)

    def test_single_transfer_recommendation(self):
        recommendation = self.optimizer.recommend_single_transfer()
        self.assertIsNotNone(recommendation)
        self.assertIn('player_out', recommendation)
        self.assertIn('player_in', recommendation)

    def test_multiple_transfer_recommendation(self):
        recommendation = self.optimizer.recommend_multiple_transfers()
        self.assertIsNotNone(recommendation)
        self.assertIsInstance(recommendation, list)
        self.assertGreater(len(recommendation), 0)

    def test_transfer_hit_analysis(self):
        hit_analysis = self.optimizer.analyze_transfer_hits()
        self.assertIsInstance(hit_analysis, dict)
        self.assertEqual(hit_analysis['hit_count'], 0)
        self.assertEqual(hit_analysis['hit_cost'], 0)
        self.assertEqual(hit_analysis['gross_gain'], 3)
        self.assertFalse(hit_analysis['should_take_hits'])

    def test_transfer_count_maximizes_net_gain_after_hits(self):
        optimizer = TransferOptimizer(
            squad=[{"id": 1, "position": "MID", "price": 7, "expected_points": 4}],
            players=[{"id": 2, "position": "MID", "price": 7, "expected_points": 7}],
            free_transfers=1,
        )

        analysis = optimizer.analyze_transfer_hits()

        self.assertEqual(analysis['transfer_count'], 1)
        self.assertEqual(analysis['hit_count'], 0)

if __name__ == '__main__':
    unittest.main()