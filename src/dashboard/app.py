from flask import Flask, render_template
import schedule
import time
from datetime import datetime
from data.fpl_api import fetch_fpl_data
from data.odds_api import fetch_odds_data
from data.fbref import fetch_fbref_data
from data.soccerdata import fetch_soccerdata
from data.news import fetch_news_data
from optimizer.transfers import recommend_transfers
from optimizer.chips import recommend_chips
from optimizer.projections import calculate_projections

app = Flask(__name__)

def get_recommendations():
    fpl_data = fetch_fpl_data()
    odds_data = fetch_odds_data()
    fbref_data = fetch_fbref_data()
    soccerdata = fetch_soccerdata()
    news_data = fetch_news_data()

    transfers = recommend_transfers(fpl_data, odds_data, fbref_data)
    chips = recommend_chips(fpl_data, odds_data)
    projections = calculate_projections(fpl_data)

    return {
        "transfers": transfers,
        "chips": chips,
        "projections": projections,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@app.route('/')
def index():
    recommendations = get_recommendations()
    return render_template('dashboard.html', recommendations=recommendations)

def job():
    print("Fetching recommendations for the upcoming game week...")
    recommendations = get_recommendations()
    # Here you would implement the logic to send notifications or update the dashboard

schedule.every().friday.at("19:00").do(job)

if __name__ == '__main__':
    while True:
        schedule.run_pending()
        time.sleep(1)
    app.run(debug=True)