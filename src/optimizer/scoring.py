from typing import List, Dict

class ScoringSystem:
    def __init__(self):
        self.points_per_action = {
            'goalkeeper': {
                'clean_sheet': 4,
                'saves': 1,
                'penalty_save': 5,
                'goal': 6,
                'own_goal': -2,
                'yellow_card': -1,
                'red_card': -3
            },
            'defender': {
                'clean_sheet': 4,
                'goal': 6,
                'own_goal': -2,
                'yellow_card': -1,
                'red_card': -3
            },
            'midfielder': {
                'goal': 5,
                'assist': 3,
                'own_goal': -2,
                'yellow_card': -1,
                'red_card': -3
            },
            'forward': {
                'goal': 4,
                'assist': 3,
                'own_goal': -2,
                'yellow_card': -1,
                'red_card': -3
            }
        }

    def calculate_points(self, player_type: str, actions: Dict[str, int]) -> int:
        total_points = 0
        for action, count in actions.items():
            if action in self.points_per_action[player_type]:
                total_points += self.points_per_action[player_type][action] * count
        return total_points

    def calculate_total_points(self, players: List[Dict[str, str]]) -> Dict[str, int]:
        total_points = {}
        for player in players:
            player_id = player['id']
            player_type = player['type']
            actions = player['actions']
            points = self.calculate_points(player_type, actions)
            total_points[player_id] = points
        return total_points