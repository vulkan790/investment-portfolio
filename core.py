import asyncio
import aiohttp
import numpy
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
    url = f"https://iss.moex.com/iss/securities/{ticker}/dividends.json?iss.only=dividends"

    try:
        data = await fetch_json(session, url)
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            print(f"Дивиденды для {ticker} не найдены (404)")
            return []
        print(f"{ticker}: HTTP {e.status}")
        return []
    except Exception as e:
        print(f"{ticker}: сетевая ошибка: {e}")
        return []

    if not isinstance(data, dict):
        print(f"{ticker}: ответ не dict, а {type(data)}")
        return []

    if "dividends" not in data:
        print(f"{ticker}: нет ключа 'dividends'. Ключи ответа: {list(data.keys())}")
        return []

    div_block = data["dividends"]
    div_data = div_block.get("data") or []
    columns = div_block.get("columns") or []

    if not div_data:
        print(f"{ticker}: секция dividends пуста")
        return []

    try:
        date_index = columns.index("registryclosedate")
        value_index = columns.index("value")
    except ValueError:
        print(f"{ticker}: неожиданные колонки: {columns}")
        return []

    result = []
    for row in div_data:
        date_str = row[date_index]
        value = row[value_index]
        if value is not None:
            result.append((date_str, float(value)))

    return result

def save_csv_sync(filename: Path, data: List[Tuple], header: List[str]) -> None:
    if not data:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(header)
        return

    first = data[0]
    fmt = ",".join("%s" if isinstance(v, str) else "%.6g" for v in first)

    arr = numpy.array(data, dtype=object)

    try:
        numpy.savetxt(filename, arr, delimiter=",", header=",".join(header), comments="", fmt=fmt, encoding="utf-8")
    except TypeError:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(data)

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

def calc_total_return(prices: numpy.ndarray, dividends: numpy.ndarray, dates: numpy.ndarray) -> numpy.ndarray:
    T = len(dates)
    shares = numpy.ones(T, dtype=numpy.float64)
    pending = numpy.zeros(T, dtype=numpy.float64)

    for i in range(1, T):
        if i >= 8:
            shares[i] = shares[i - 1] + pending[i - 8] / prices[i]
        else:
            shares[i] = shares[i - 1]

        if dividends[i] > 0 and i + 8 < T:
            pending[i + 8] += shares[i] * dividends[i]

    return numpy.column_stack([dates.astype(str), prices, shares, shares * prices])

def load_prices(ticker: str) -> Tuple[numpy.ndarray, numpy.ndarray]:
    dates, prices = [], []
    file_path = f"data/{ticker}_prices.csv"

    with open(file_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)

        for row in reader:
            dates.append(row[0])
            prices.append(float(row[1]))

    return (
        numpy.array(dates, dtype="datetime64[D]"),
        numpy.array(prices, dtype=numpy.float64)
    )

def load_dividends(ticker: str) -> Tuple[numpy.ndarray, numpy.ndarray]:
    dates, value = [], []
    file_path = f"data/{ticker}_dividends.csv"

    try:
        with open(file_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)

            for row in reader:
                dates.append(row[0])
                value.append(float(row[1]))

    except FileNotFoundError:
        return (
            numpy.array([], dtype="datetime64[D]"),
            numpy.array([], dtype=numpy.float64)
        )

    d = numpy.array(dates, dtype="datetime64[D]")
    v = numpy.array(value, dtype=numpy.float64)

    order = numpy.argsort(d)
    return d[order], v[order]

def load_ticker_data(ticker: str) -> Tuple[str, numpy.ndarray, numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    dates, prices = load_prices(ticker)
    div_dates, div_values = load_dividends(ticker)
    return ticker, dates, prices, div_dates, div_values

async def build_common_calendar(tickers: list, executor: ThreadPoolExecutor) -> Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    loop = asyncio.get_running_loop()
    tasks = [loop.run_in_executor(executor, load_ticker_data, t) for t in tickers]
    results = await asyncio.gather(*tasks)

    if not results:
        return (
            numpy.array([], dtype="datetime64[D]"),
            numpy.zeros((0, len(tickers)), dtype=numpy.float64),
            numpy.zeros((0, len(tickers)), dtype=numpy.float64),
        )

    all_dates = [r[1] for r in results]

    common = all_dates[0]
    for d in all_dates[1:]:
        common = numpy.intersect1d(common, d)

    T = len(common)
    N = len(tickers)
    price_mat = numpy.zeros((T, N), dtype=numpy.float64)
    div_mat = numpy.zeros((T, N), dtype=numpy.float64)

    for j, (_, dates, p_arr, div_dates, div_values) in enumerate(results):
        idx = numpy.searchsorted(dates, common)
        idx_c = numpy.clip(idx, 0, len(dates) - 1)
        valid = (idx < len(dates)) & (dates[idx_c] == common)
        price_mat[valid, j] = p_arr[idx[valid]]

        if len(div_dates) > 0:
            idx_d = numpy.searchsorted(div_dates, common)
            idx_dc = numpy.clip(idx_d, 0, len(div_dates) - 1)
            valid_d = (idx_d < len(div_dates)) & (div_dates[idx_dc] == common)
            div_mat[valid_d, j] = div_values[idx_d[valid_d]]

    return common, price_mat, div_mat

def build_common_calendar_sync(tickers: List[str]) -> Tuple[numpy.ndarray, numpy.ndarray, numpy.ndarray]:
    loaded = []
    all_dates = []
    for t in tickers:
        _, dates, p_arr, div_dates, div_values = load_ticker_data(t)
        loaded.append((t, dates, p_arr, div_dates, div_values))
        all_dates.append(dates)

    if not all_dates:
        return (
            numpy.array([], dtype="datetime64[D]"),
            numpy.zeros((0, len(tickers)), dtype=numpy.float64),
            numpy.zeros((0, len(tickers)), dtype=numpy.float64),
        )

    common = all_dates[0]
    for d in all_dates[1:]:
        common = numpy.intersect1d(common, d)

    T = len(common)
    N = len(tickers)

    price_mat = numpy.zeros((T, N), dtype=numpy.float64)
    div_mat = numpy.zeros((T, N), dtype=numpy.float64)

    for j, (t, dates, p_arr, div_dates, div_values) in enumerate(loaded):
        idx = numpy.searchsorted(dates, common)
        idx_c = numpy.clip(idx, 0, len(dates) - 1)
        valid = (idx < len(dates)) & (dates[idx_c] == common)
        price_mat[valid, j] = p_arr[idx[valid]]

        if len(div_dates) > 0:
            idx_d = numpy.searchsorted(div_dates, common)
            idx_dc = numpy.clip(idx_d, 0, len(div_dates) - 1)
            valid_d = (idx_d < len(div_dates)) & (div_dates[idx_dc] == common)
            div_mat[valid_d, j] = div_values[idx_d[valid_d]]

    return common, price_mat, div_mat

def simulate_portfolio(common_data: numpy.ndarray, price_mat: numpy.ndarray, div_mat: numpy.ndarray, tickers: List[str], monthly_amount: float) -> Tuple[numpy.ndarray, numpy.ndarray]:
    T, N = price_mat.shape
    assert len(common_data) == T, "common_data и price_mat рассинхронизированы"

    months = common_data.astype("datetime64[M]")
    topup = numpy.concatenate(([True], months[1:] != months[:-1]))

    shares = numpy.zeros(N, dtype=numpy.float64)
    pending = numpy.zeros((T, N), dtype=numpy.float64)
    total_invested = 0.0
    result = numpy.zeros((T, 3), dtype=numpy.float64)

    for i in range(T):
        if topup[i]:
            shares += (monthly_amount / N) / price_mat[i]
            total_invested += monthly_amount

        if i >= 8:
            shares += pending[i - 8] / price_mat[i]
        if i + 8 < T:
            pending[i + 8] += shares * div_mat[i]

        result[i] = (i, shares @ price_mat[i], total_invested)

    return common_data, result