# AgriValue: ML-Based Crop Price and Net Return Analysis System

**Smarter Decisions for a More Profitable Harvest**

AgriValue helps users compare agricultural market price estimates and calculate expected revenue and estimated net return before selling. It is a Flask decision-support project for a B.Tech final-year demonstration.

## Problem and objective

Agricultural prices can differ across markets. AgriValue uses historical market records and a supervised regression model to estimate a commodity's modal price. The application then combines that estimate with the user's quantity and transportation-cost input to calculate expected revenue and estimated net return.

The application supports every commodity in the current workbook. Results are estimates, not guarantees or recommendations.

## Dataset

The master dataset is data/agri_value_market_data_final.xlsx. The application reads the first worksheet and leaves the workbook unchanged. A cleaned working copy is written separately to data/processed/clean_market_data.csv.

The inspected workbook has **10,272 rows and 16 columns**. It contains 211 commodities, 17 states, 322 districts, 1,118 markets, 392 varieties, and 5 grades. The exact fields are:

State, District, Market, Commodity, Variety, Grade, Arrival_Date, Min_Price, Max_Price, Modal_Price, Commodity_Code, Price_Stability, Market_Activity, Market_Size, District_Region, and Price_Unit.

The actual source price units are ₹/quintal and ₹/number. Revenue calculations use a supported matching quantity unit: for a quintal price, quantity can be entered in kg (converted by dividing by 100) or quintals; for a number price, quantity must be a count. Unsupported or mismatched unit combinations are rejected instead of guessed. Transportation cost is entered by the user and is not part of the workbook.

### Dataset coverage and cleaning

The valid date coverage in this workbook is 01 Jan 2025 only. 10,000 records have a valid date and 272 do not. There are 27 exact duplicate rows. The cleaned working copy excludes exact duplicates and rows with invalid required values or inconsistent prices; it keeps undated rows and reports statistical outliers rather than automatically dropping them. The master workbook remains unchanged.

## Machine-learning method

- **Target:** Modal_Price
- **Model:** Linear Regression wrapped in a scikit-learn pipeline with a log-transformed target
- **Input features:** Commodity, State, District, Market, Variety, Grade, District_Region, and Price_Unit
- **Preprocessing:** one-hot encoding of categorical inputs; infrequent categories grouped; unknown values ignored; missing categories represented as Unknown
- **Leakage review:** Modal_Price is not an input. Min_Price and Max_Price describe the same observation and are excluded. The identifier, observation date, and source summary labels are excluded from training.
- **Split:** seeded 80/20 random holdout because the current dataset contains only one distinct valid date. These metrics do not demonstrate future-price accuracy.

Current evaluation after training on the finalized workbook:

| Metric | Value |
|---|---:|
| Training records | 8,196 |
| Testing records | 2,049 |
| MAE | 1,310.78 |
| RMSE | 4,484.19 |
| R² | 0.6703 |

Metrics are calculated by utils/model_training.py and saved in models/model_metadata.json; they are not hard-coded in the dashboard.

## Main features

- Dynamic state, district, market, commodity, variety, and grade filters based on workbook records
- Model-estimated market prices with each actual source price unit displayed
- Market comparison with historical source information
- Expected revenue and estimated net return using quantity and user-entered transportation cost
- Historical price stability calculations using mean, minimum, maximum, sample standard deviation, and coefficient of variation
- Quantity range calculations with expected revenue, fixed transportation cost, estimated net return, and difference from the prior quantity
- CSV, Excel, and PDF reports for the current analysis
- Dynamic dataset summary, model information, and responsive green-and-white dashboard

The price-stability label in the workbook is shown as a source label. Calculated coefficient of variation is presented separately. Price variability describes available records; it is not a forecast of future risk.

## Technology

Python, Flask, Pandas, NumPy, scikit-learn, joblib, HTML, CSS, JavaScript, Chart.js, openpyxl, and ReportLab.

## Installation and running

From the project folder in PowerShell:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
~~~

Open http://127.0.0.1:5000/.

To retrain the model from the current workbook:

~~~powershell
python -m utils.model_training
~~~

## Project structure

~~~text
agri_value/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── agri_value_market_data_final.xlsx
│   └── processed/
│       └── clean_market_data.csv
├── models/
│   ├── price_model.pkl
│   └── model_metadata.json
├── utils/
│   ├── data_processing.py
│   ├── model_training.py
│   ├── prediction.py
│   ├── calculations.py
│   └── reporting.py
├── templates/
├── static/
└── tests/
~~~

## Verification

Run the project checks with:

~~~powershell
python -m unittest discover -s tests -v
~~~

The Flask routes include Home, Market Analysis, prediction, calculation, Results, Visual Analysis, Reports/Downloads, Model Information, Dataset Summary, and About.

## Limitations

- The workbook has one distinct valid date, so it cannot support reliable long-term forecasting or a meaningful time-based chart.
- Model estimates reflect the available historical records and may not match future market prices.
- Transportation cost is user-entered and treated as a fixed comparison cost.
- Actual unit conversions are limited to explicitly supported combinations.
- The system provides decision support and does not guarantee a sale, price, revenue, or profit.

## Future enhancements

More crops and historical years, additional verified price units, real-time market data, more accurate transport estimates, weather context, regional-language support, voice interaction, progressive web app improvements, and additional market costs can be considered in later versions.

