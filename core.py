import asyncio
import aiohttp
import csv
from concurrent.futures import *
from datetime import *
from pathlib import *
from typing import *

FILE = "tickers"
OUTPUT_DIR = Path("data")
MAX_CONCURRENT_REQUEST = 5
REQUEST_DELAY = 0.1

async def ticket_generator(file_path: str) -> AsyncGenerator[str, None]:
    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(None, Path(file_path).read_text, "utf-8")
    for line in content.splitlines():
        ticker = line.strip()
        if ticker and not ticker.startswith("#"):
            yield ticker.upper()

async def fetch_json(session: aiohttp.ClientSession, url: str, params: dict = None) -> dict[str, Any]:
    async with session.get(url, params=params) as resp:
        resp.raise_for_status()
        return await resp.json()

async def get_date_bounds(session: aiohttp.ClientSession, ticker: str) -> Tuple[str, str]:
    url = f"http://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/dates.json"
    data = await fetch_json(session, url)
    dates = data["dates"]["data"]
    if not dates:
        raise ValueError(f"Нет доступных для {ticker}")
    return dates[0][0], dates[0][1]

async def fetch_prices(session: aiohttp.ClientSession, ticker: str, semaphore: asyncio.Semaphore) -> List[Tuple[str, float]]:
    date_from, _ = await get_date_bounds(session, ticker)
    current_from = date_from
    all_prices: List[Tuple[str, float]] = []
    while True:
        url = f"http://iss.moex.com/iss/history/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
        params = {
            "from": current_from,
            "limit": 100
        }

        async with semaphore:
            data = await fetch_json(session, url, params)

        history = data["history"]["data"]
        if not history:
            break

        columns = data["history"]["columns"]
        try:
            close_index = columns.index("CLOSE")
            date_index = columns.index("TRADEDATE")
        except ValueError:
            print(f"Ошибка: колонки цен не найдены для {ticker}")
            break

        for row in history:
            date_str = row[date_index]
            price = row[close_index]

            if price is not None:
                all_prices.append((date_str, float(price)))

        if len(history) < 100:
            break

        last_date = datetime.strptime(history[-1][date_index], "%Y-%m-%d")
        current_from = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        await asyncio.sleep(REQUEST_DELAY)

    return all_prices

async def fetch_dividends(session: aiohttp.ClientSession, ticker: str) -> List[Tuple[str, float]]:
    url = f"http://iss.moex.com/iss/securities/{ticker}/dividends.json"
    try:
        data = await fetch_json(session, url)
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            print(f"Дивиденды для {ticker} не найдены (404)")
            return []
        raise

    div_data = data["dividends"]["data"]
    columns = data["dividends"]["columns"]

    try:
        date_index = columns.index("registryclosedate")
        value_index = columns.index("value")
    except ValueError:
        print(f"Ошибка: неожиданная структура дивидентов для {ticker}")
        return []

    result = []
    for row in div_data:
        date_str = row[date_index]
        value = row[value_index]

        if value is not None:
            result.append((date_str, float(value)))

    return result

def save_csv_sync(filename: Path, data: List[Tuple], header: List[str]) -> None:
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data)

async def save_csv_async(executor: ThreadPoolExecutor, filename: Path, data: List[Tuple], header: List[str]) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, save_csv_sync, filename, data, header)

async def process_ticker(session: aiohttp.ClientSession, executor: ThreadPoolExecutor, semaphore: asyncio.Semaphore, ticker: str) -> None:
    print(f"Обрабатывается {ticker}")
    try:
        prices = await fetch_prices(session, ticker, semaphore)
        if prices:
            await save_csv_async(executor, OUTPUT_DIR / f"{ticker}_prices.csv", prices, ["Date", "Close"])
            print(f"Сохранено {len(prices)} цен")
        else:
            print("Цены не получены")

        dividends = await fetch_dividends(session, ticker)
        if dividends:
            await save_csv_async(executor, OUTPUT_DIR / f"{ticker}_dividends.csv", dividends, ["Date", "Dividend"])
            print(f"Сохранено {len(dividends)} дивидендов")
        else:
            print("Дивиденды не получены")
    except Exception as e:
        print(f"Непредвиденная ошибка при обработке {ticker}: {e}")

def calc_total_return(prices_dict: dict, dividends_dict: dict, dates: list) -> List[Tuple[date, float, float, float]]:
    shares = 1.0
    pending_divs = {}
    result = []

    for i, cur_date in enumerate(dates):
        if cur_date in pending_divs:
            cash = pending_divs.pop(cur_date)
            shares += cash / prices_dict[cur_date]

        if cur_date in dividends_dict:
            total_div = shares * dividends_dict[cur_date]
            if (i + 8) < len(dates):
                credit_date = dates[i + 8]
                pending_divs[credit_date] = pending_divs.get(credit_date, 0.0) + total_div
        result.append((cur_date, prices_dict[cur_date], shares, shares * prices_dict[cur_date]))

    return result

def load_prices(ticker: str) -> Tuple[dict, list]:
    prices_dict = {}
    dates = []
    file_path = f"data/{ticker}_prices.csv"

    with open(file_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)

        for row in reader:
            date_str = row[0]
            price_str = row[1]

            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
            price_obj = float(price_str)

            prices_dict[date_obj] = price_obj
            dates.append(date_obj)

    return prices_dict, dates

def load_dividends(ticker: str) -> dict:
    dividends_dict = {}
    file_path = f"data/{ticker}_dividends.csv"

    try:
        with open(file_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)

            for row in reader:
                date_str = row[0]
                dividends_str = row[1]

                date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
                dividends_obj = float(dividends_str)

                dividends_dict[date_obj] = dividends_obj

        return dividends_dict
    except FileNotFoundError:
        return {}

def load_ticker_data(ticker: str) -> Tuple[str, Dict[date, float], List[date], Dict[date, float]]:
    prices_dict, dates = load_prices(ticker)
    dividends_dict = load_dividends(ticker)
    return ticker, prices_dict, dates, dividends_dict

async def build_common_calendar(tickers: list, executor: ThreadPoolExecutor) -> Tuple[List[date], Dict[str, Dict[date, float]], Dict[str, Dict[date, float]]]:
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(executor, load_ticker_data, t) for t in tickers]
    results = await asyncio.gather(*tasks)

    prices: Dict[str, Dict[date, float]] = {}
    dividends: Dict[str, Dict[date, float]] = {}
    all_date_sets: List[Set[date]] = []

    for ticker, p_dict, d_list, div_dict in results:
        prices[ticker] = p_dict
        dividends[ticker] = div_dict
        all_date_sets.append(set(d_list))

    if not all_date_sets:
        return [], prices, dividends

    common_data_set = all_date_sets[0].intersection(*all_date_sets[1:])
    common_data = sorted(common_data_set)

    return common_data, prices, dividends


def build_common_calendar_sync(tickers: List[str]) -> Tuple[
    List[date], Dict[str, Dict[date, float]], Dict[str, Dict[date, float]]]:
    prices: Dict[str, Dict[date, float]] = {}
    dividends: Dict[str, Dict[date, float]] = {}
    all_date_sets: List[set] = []

    for t in tickers:
        _, p_dict, d_list, div_dict = load_ticker_data(t)
        prices[t] = p_dict
        dividends[t] = div_dict
        all_date_sets.append(set(d_list))

    if not all_date_sets:
        return [], prices, dividends

    common = all_date_sets[0].intersection(*all_date_sets[1:])
    return sorted(common), prices, dividends

def simulate_portfolio(common_data: List[date], prices: Dict[str, Dict[date, float]], dividends: Dict[str, Dict[date, float]], tickers: List[str], monthly_amount: float) -> List[Tuple[date, float, float]]:
    topup_dates = set()
    current_month = None

    for data in common_data:
        month_key = (data.year, data.month)
        if month_key != current_month:
            topup_dates.add(data)
            current_month = month_key

    shares = {t: 0.0 for t in tickers}
    pending_divs = {t: {} for t in tickers}
    total_invested = 0.0
    result = []

    for i, data in enumerate(common_data):
        if data in topup_dates:
            amount_per_company = monthly_amount / len(tickers)
            for t in tickers:
                shares[t] += amount_per_company / prices[t][data]
            total_invested += monthly_amount

        for t in tickers:
            if data in pending_divs[t]:
                shares[t] += pending_divs[t].pop(data) / prices[t][data]
            if data in dividends[t]:
                div_amount = shares[t] * dividends[t][data]
                if (i + 8) < len(common_data):
                    credit_data = common_data[i + 8]
                    pending_divs[t][credit_data] = pending_divs[t].get(credit_data, 0.0) + div_amount

        total_value = sum(shares[t] * prices[t][data] for t in tickers)
        result.append((data, total_value, total_invested))

    return result