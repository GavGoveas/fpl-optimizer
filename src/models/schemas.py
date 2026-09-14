from pydantic import BaseModel
from typing import List, Optional

class Player(BaseModel):
    id: int
    name: str
    position: str
    team: str
    price: float
    points: int
    form: float
    fixtures: List[str]

class Team(BaseModel):
    id: int
    name: str
    players: List[Player]

class TransferRecommendation(BaseModel):
    player_out: Player
    player_in: Player
    reason: str

class ChipRecommendation(BaseModel):
    chip_type: str
    players: List[Player]
    reason: str

class GameWeekData(BaseModel):
    game_week: int
    transfers: List[TransferRecommendation]
    chip_usage: List[ChipRecommendation]
    projected_points: Optional[float] = None