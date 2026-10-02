# Investment Portfolio

Сервис (учебный) для демонстрации преимуществ стратегии "купил и держи" на российском фондовом рынке.

## Возможности 

- Загрузка исторических данных котировок и дивидендов с API Московской биржи
- Расчёт цены полной доходности с учётом реинвестирования дивидендов
- Моделирование стратегии ежемесячного пополнения портфеля
- Графическая визуализация результатов
- Интерактивный GUI на PyQt5 с выбором тикеров

## Стек

- **Python** - язык программирования
- **NumPy** - вся математика портфеля (матрицы цен, матричное умножение и другие операции)
- **pandas** - I/O и выравнивание данных (Загрузка CSV, общий календарь)
- **aiohttp** - HTTP - запросы
- **PyQt5 + Qt Designer** - GUI
- **matplotlib** - графики
- **API Московской биржи (ISS MOEX)** - данные
- **CSV** - формат данных

## Установка и запуск

1) Клонировать репозиторий

```
git clone https://github.com/vulkan790/investment-portfolio.git
cd investment-portfolio
```

2) Установить все требуемые зависимости

```
pip install aiohttp numpy pandas matplotlib PyQt5
```

3) Запустить GUI

```
python main.py
```

## Структура

```
├── main.py              # Точка входа (запуск GUI)
├── gui.py               # Класс MainWindow (интерфейс)
├── core.py              # Загрузка данных и расчёт портфеля
├── main_window.ui       # Файл интерфейса Qt Designer
├── tickers              # Список тикеров (15 российских компаний)
├── portfolio_data.csv   # Пример сохранённой таблицы
├── portfolio_graph.png  # Пример сохранённого графика
└── README.md            # Документация
```

## Как устроено ядро

- `build_common_calendar_sync` загружает тикеры через `pandas.read_csv`
  и выравнивает их по общему торговому календарю через
  `pandas.DataFrame(dict).dropna()` + `.reindex().fillna(0)`.
- На выходе - две матрицы NumPy: `price_mat (T, N)` и `div_mat (T, N)`.
- `simulate_portfolio` итерирует по дням, использует:
  - `numpy.concatenate` для маски ежемесячных пополнений,
  - `@` (матричное умножение) для стоимости портфеля,
  - broadcasting для реинвестирования дивидендов,
  - `datetime64[M]` для определения первого торгового дня месяца.
- Экспорт - `pandas.DataFrame.to_csv` (смешанные типы из коробки).

## Интерфейс

1) Выберите 5 тикеров в выпадающих списках (все разные)
2) Установите ежемесячный взнос (по умолчанию 10 000 ₽)
3) Нажмите «Рассчитать» - построится график стоимости портфеля
4) Нажмите «Сохранить график» - экспорт в PNG (сохраниться в папке с проектом)

## Стратегия инвестирования

- Ежемесячное пополнение на фиксированную сумму
- Равное распределение между 5 выбранными компаниями
- Реинвестирование дивидендов в ту же компанию (через 8 торговых дней)
- Игнорирование налогов и комиссий (учебное допущение)
- Покупка дробных акций разрешена

## Примечания
- Проект учебный, не является инвестиционной рекомендацией
- Историческая доходность не гарантирует будущих результатов
- Данные предоставлены Московской биржей (ISS MOEX API)

# Investment Portfolio

An educational service demonstrating the benefits of the "buy and hold" strategy on the Russian stock market.

## Features

- Download historical stock prices and dividends from Moscow Exchange API
- Calculate total return including dividend reinvestment
- Simulate a monthly portfolio contribution strategy
- Graphical visualization of results
- Interactive PyQt5 GUI with ticker selection

## Stack

- **Python** - programming language
- **NumPy** - all mathematics of the portfolio (price matrices, matrix multiplication and other operations)
- **pandas** - I/O and data alignment (Import CSV, common calendar)
- **aiohttp** - HTTP requests
- **PyQt5 + Qt Designer** - GUI
- **matplotlib** - charts
- **Moscow Exchange API (ISS MOEX)** - data source
- **CSV** - data format

## Installation and launch

1) Clone the repository

```
git clone https://github.com/vulkan790/investment-portfolio.git
cd investment-portfolio
```

2) Install all required dependencies

```
pip install aiohttp numpy pandas matplotlib PyQt5
```

3) Launch the GUI

```
python main.py
```

## Structure

```
├── main.py               # Entry point (GUI launch)
├── gui.py                # MainWindow class (interface)
├── core.py               # Data loading and portfolio calculation
├── main_window.ui        # Qt Designer interface file
├── tickers               # Ticker list (15 Russian companies)
├── portfolio_data.csv    # Example of a saved table
├── portfolio_graph.png   # Example of a saved chart
└── README.md             # Documentation
```

## Core design

- `build_common_calendar_sync` loads tickers via `pandas.read_csv`
  and aligns them to a common trading calendar via
  `pandas.DataFrame(dict).dropna()` + `.reindex().fillna(0)`.
- Returns two NumPy matrices: `price_mat (T, N)` and `div_mat (T, N)`.
- `simulate_portfolio` iterates over days and uses:
  - `numpy.concatenate` to build the monthly top-up mask,
  - `@` (matrix multiplication) for portfolio value,
  - broadcasting for dividend reinvestment,
  - `datetime64[M]` to detect the first trading day of the month.
- Export - `pandas.DataFrame.to_csv` (mixed types out of the box).

## Interface

1) Select 5 tickers from the dropdown lists (all must be different)
2) Set the monthly contribution (default: 10,000 RUB)
3) Click "Calculate" — a portfolio value chart will be displayed
4) Click "Save Chart" — exports the chart as PNG (saved in the project folder)

## Investment Strategy

- Monthly fixed-amount contributions
- Equal distribution among 5 selected companies
- Dividend reinvestment into the same company (after 8 trading days)
- Taxes and commissions ignored (educational assumption)
- Fractional shares allowed

## Notes

- This is an educational project, not investment advice
- Past performance does not guarantee future results
- Data provided by Moscow Exchange (ISS MOEX API)
