# FPL Optimizer

## Overview
The FPL Optimizer is an automated tool designed to assist Fantasy Premier League (FPL) managers in making informed decisions regarding transfers, chip usage, and overall team management. By leveraging data from various APIs, the optimizer provides recommendations based on player performance, upcoming fixtures, and injury updates.

## Features
- **Automated Transfer Recommendations**: Suggests optimal transfers each game week, including single and multiple transfers based on player form and fixtures.
- **Chip Management**: Provides guidance on when to use chips such as Triple Captain, Bench Boost, Free Hit, and Wildcard.
- **Data Integration**: Utilizes data from the official FPL API, odds API, FBRef, SoccerData, and Gemini RSS for injury updates.
- **Scheduled Notifications**: Sends recommendations every Friday at 19:00 IST to keep managers informed.

## Project Structure
```
fpl-optimizer
├── src
│   ├── main.py               # Entry point for the application
│   ├── config.py             # Configuration settings and API keys
│   ├── data
│   │   ├── fpl_api.py        # Interacts with the official FPL API
│   │   ├── odds_api.py       # Connects to the odds API for market data
│   │   ├── fbref.py          # Fetches player statistics from FBRef
│   │   ├── soccerdata.py     # Retrieves additional soccer data
│   │   └── news.py           # Processes injury updates from Gemini RSS
│   ├── optimizer
│   │   ├── transfers.py       # Logic for determining optimal transfers
│   │   ├── chips.py           # Manages chip usage recommendations
│   │   ├── projections.py      # Calculates player projections and expected points
│   │   └── scoring.py         # Defines scoring system and calculates points
│   ├── dashboard
│   │   └── app.py            # Sets up the web dashboard for recommendations
│   ├── notifications
│   │   └── scheduler.py       # Handles scheduling of notifications
│   └── models
│       └── schemas.py        # Defines data schemas for consistency
├── tests
│   ├── test_optimizer.py      # Unit tests for optimizer logic
│   └── test_data_sources.py    # Unit tests for data retrieval functions
├── .env.example               # Example of environment variables
├── .gitignore                 # Specifies files to ignore by Git
├── requirements.txt           # Lists Python dependencies
├── pyproject.toml            # Project metadata and configuration
└── README.md                  # Documentation for the project
```

## Installation
1. Clone the repository:
   ```
   git clone <repository-url>
   cd fpl-optimizer
   ```
2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up your environment variables by copying `.env.example` to `.env` and adding your API keys.

## Usage
To run the optimizer, execute the following command:
```
python src/main.py
```
The dashboard will be available at `http://localhost:5000`, displaying the latest recommendations for your FPL team.

## Contributing
Contributions are welcome! Please open an issue or submit a pull request for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.