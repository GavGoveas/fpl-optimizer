from config import API_KEYS
from data.fpl_api import FPLAPI
from data.odds_api import OddsAPI
from data.fbref import FBRef
from data.soccerdata import SoccerData
from data.news import News
from optimizer.transfers import Transfers
from optimizer.chips import Chips
from optimizer.projections import Projections
from optimizer.scoring import Scoring
from dashboard.app import Dashboard
from notifications.scheduler import Scheduler

def main():
    # Initialize APIs
    fpl_api = FPLAPI(API_KEYS['FPL_API_KEY'])
    odds_api = OddsAPI(API_KEYS['ODDS_API_KEY'])
    fbref = FBRef()
    soccerdata = SoccerData()
    news = News()

    # Initialize optimizer components
    transfers = Transfers(fpl_api, odds_api)
    chips = Chips(fpl_api)
    projections = Projections(fpl_api, fbref)
    scoring = Scoring()

    # Initialize dashboard
    dashboard = Dashboard(transfers, chips, projections, scoring)

    # Schedule notifications
    scheduler = Scheduler(dashboard)
    scheduler.schedule_notifications()

    # Start the dashboard
    dashboard.run()

if __name__ == "__main__":
    main()