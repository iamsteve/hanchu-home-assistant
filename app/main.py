import os
import time
import json
import threading
import logging
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn
import nest_asyncio

# Load environment variables
load_dotenv()

USERNAME = os.getenv("HANCHU_USERNAME")
PASSWORD = os.getenv("HANCHU_PASSWORD")
LOGIN_URL = os.getenv("LOGIN_URL")

if not USERNAME or not PASSWORD or not LOGIN_URL:
    raise EnvironmentError("Missing required environment variables.")

# Constants
FETCH_INTERVAL = 30  # seconds
WATT_CONVERSION = 1000
DIVISOR = 120

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# In-memory data store
latest_data = {}
data_lock = threading.Lock()

# FastAPI setup
app = FastAPI()

@app.get("/api/data")
def get_data():
    with data_lock:
        if latest_data:
            return JSONResponse(content=latest_data)
        else:
            return JSONResponse(content={"error": "Data not available yet"}, status_code=503)

def create_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-browser-side-navigation")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--remote-debugging-port=9222")
    return webdriver.Chrome(options=options)

def login(driver):
    logging.info("Attempting login...")
    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 20)

    wait.until(EC.presence_of_element_located((By.ID, "account"))).find_element(By.TAG_NAME, "input").send_keys(USERNAME)
    wait.until(EC.presence_of_element_located((By.ID, "pwd"))).find_element(By.TAG_NAME, "input").send_keys(PASSWORD)
    wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "login-btn"))).click()

def extract_float(text):
    try:
        return float(text)
    except ValueError:
        return 0.0

def format_decimal(value):
    """Formats a float to a string with 5 decimal places, handling the zero case."""
    if value == 0.0:
        return "0.000"
    return f"{value:.5f}"

def fetch_data(driver):
    wait = WebDriverWait(driver, 10)

    scene = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "scene")))
    spans = scene.find_elements(By.TAG_NAME, "span")

    # A check to ensure we have enough spans, to avoid IndexError
    if len(spans) < 8:
        span_texts = [s.text for s in spans]
        logging.error(f"Expected at least 8 span elements, but found {len(spans)}. Content: {span_texts}")
        # The code will raise an IndexError below, which is handled by the main loop's retry mechanism.
        # This is better than silently failing or processing incorrect data.

    stream_images = scene.find_elements(By.CLASS_NAME, "stream-img")

    bat_status = scene.find_element(By.CLASS_NAME, "bat-status").text
    unit = scene.find_element(By.CLASS_NAME, "unit").text
    battery_percentage = scene.find_element(By.CLASS_NAME, "progress-wrap").find_element(By.CLASS_NAME, "text").text.replace('.0%', '')

    grid_status = "Idle"
    grid_production = 0.0
    grid_usage = 0.0

    for img in stream_images:
        src = img.get_attribute("src")
        if "grid-in" in src:
            grid_status = "Importing"
            grid_usage = extract_float(spans[5].text)
            break
        elif "grid-out" in src:
            grid_status = "Exporting"
            grid_production = extract_float(spans[5].text)
            break

    solar = extract_float(spans[1].text)
    home = extract_float(spans[3].text)

    battery_export = 0.0
    battery_import = 0.0
    battery_flow = extract_float(spans[7].text)

    if bat_status == "Charge":
        battery_import = battery_flow
    elif bat_status == "Discharge":
        battery_export = battery_flow

    unit_multiplier = WATT_CONVERSION if unit == "W" else 1
    convert = lambda x: (x / DIVISOR) / unit_multiplier

    result = {
        'solar_production': format_decimal(convert(solar)),
        'home_usage': format_decimal(convert(home)),
        'grid_status': grid_status,
        'grid_usage': format_decimal(convert(grid_usage)),
        'grid_production': format_decimal(convert(grid_production)),
        'battery_export': format_decimal(convert(battery_export)),
        'battery_import': format_decimal(convert(battery_import)),
        'battery_status': bat_status,
        'battery_percentage': battery_percentage
    }

    with data_lock:
        global latest_data
        latest_data = result

    logging.info("Data fetched and saved.")

def run_monitor():
    driver = create_driver()
    try:
        login(driver)
        fetch_data(driver)
        time.sleep(FETCH_INTERVAL)

        while True:
            try:
                driver.refresh()
                fetch_data(driver)
            except Exception as e:
                logging.warning(f"Error occurred: {e}. Retrying login.")
                login(driver)
                fetch_data(driver)
            time.sleep(FETCH_INTERVAL)
    finally:
        driver.quit()

def start_server():
    uvicorn.run(app, host="0.0.0.0", port=5322)

# Bootstrap
nest_asyncio.apply()
threading.Thread(target=start_server, daemon=True).start()
run_monitor()
