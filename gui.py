import pandas
import matplotlib.pyplot as plt
from PyQt5 import uic
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMainWindow, QApplication, QVBoxLayout
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from core import *

class PortfolioWorker(QThread):
    done = pyqtSignal(object, object)
    error = pyqtSignal(object)

    def __init__(self, tickers, monthly):
        super().__init__()
        self.tickers = tickers
        self.monthly = monthly

    def run(self):
        try:
            common_dates, price_mat, div_mat = build_common_calendar_sync(self.tickers)
            dates_arr, result = simulate_portfolio(common_dates, price_mat, div_mat, self.tickers, self.monthly)
            self.done.emit(dates_arr, result)
        except Exception as e:
            self.error.emit(str(e))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        uic.loadUi("main_window.ui", self)

        self.all_tickers = self._load_tickers_from_file()

        combos = [self.comboTicker1, self.comboTicker2, self.comboTicker3, self.comboTicker4, self.comboTicker5]
        for combo in combos:
            combo.addItems(self.all_tickers)
            combo.currentTextChanged.connect(self._validate_tickers)

        self.spinMonthly.setValue(10_000)
        self.spinMonthly.setSingleStep(1_000)
        self.figure = Figure(figsize=(8, 5))
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout(self.graphWidget)
        layout.addWidget(self.canvas)

        self.btnCalculate.clicked.connect(self.on_calculate)
        self.btnSave.clicked.connect(self.on_save)
        self.btnSave.setEnabled(False)
        self.labelTotal.setText("Итоговая стоимость: 0 руб.")
        self.current_result = None
        self.current_dates = None
        self.worker = None
        self.btnClear.clicked.connect(self.on_clear)

    def _load_tickers_from_file(self) -> List[str]:
        try:
            text = Path("tickers").read_text("utf-8")
            tickers = []
            for line in text.splitlines():
                t = line.strip().upper()
                if t and not t.startswith("#"):
                    tickers.append(t)
            return tickers
        except FileNotFoundError:
            return ["SBER", "LKOH", "GMKN", "PHOR", "YNDX"]

    def _validate_tickers(self):
        selected = self.get_selected_tickers()
        unique = len(set(selected)) == 5 and all(selected)

        if not unique:
            self.labelStatus.setText("Выберите 5 уникальных тикеров")
            self.btnCalculate.setEnabled(False)
        else:
            self.labelStatus.setText("Тикеры выбраны")
            self.btnCalculate.setEnabled(True)

    def get_selected_tickers(self) -> List[str]:
        return [
            self.comboTicker1.currentText(),
            self.comboTicker2.currentText(),
            self.comboTicker3.currentText(),
            self.comboTicker4.currentText(),
            self.comboTicker5.currentText(),
        ]

    def on_calculate(self):
        tickers = self.get_selected_tickers()
        monthly = self.spinMonthly.value()

        if len(set(tickers)) != 5 or "" in tickers:
            self.labelStatus.setText("Ошибка: выберите 5 разных тикеров")
            return

        if self.worker is not None and self.worker.isRunning():
            return

        self.labelStatus.setText("Идёт расчёт...")
        self.btnCalculate.setEnabled(False)
        self.btnClear.setEnabled(False)
        self.btnSave.setEnabled(False)

        self.worker = PortfolioWorker(tickers, monthly)
        self.worker.done.connect(self._on_calc_done)
        self.worker.error.connect(self._on_calc_error)
        self.worker.start()

    def _on_calc_done(self, dates_arr, result):
        self.current_result = result
        self.current_dates = dates_arr
        self._plot_result(dates_arr, result)

        final_value = float(result[-1, 1])
        total_invested = float(result[-1, 2])
        profit = final_value - total_invested

        self.labelTotal.setText(f"Итог: {final_value:,.0f} руб. | " f"Внесено: {total_invested:,.0f} руб. | " f"Прибыль: {profit:,.0f} руб.")
        self.labelStatus.setText("Расчёт завершён")
        self.btnCalculate.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.btnSave.setEnabled(True)

        self.statusbar.showMessage(f"Период: {dates_arr[0]} — {dates_arr[-1]} | " f"Доходность: {(profit / total_invested * 100):.1f}%")

    def _on_calc_error(self, msg):
        self.labelStatus.setText(f"Ошибка: {msg[:60]}")
        self.statusbar.showMessage(f"Ошибка: {msg}")
        self.btnCalculate.setEnabled(True)
        self.btnClear.setEnabled(True)
        self.btnSave.setEnabled(False)

    def _plot_result(self, dates: numpy.ndarray, result: numpy.ndarray):
        values = result[:, 1]
        invested = result[:, 2]

        self.figure.clear()

        ax = self.figure.add_subplot(111)
        ax.plot(dates, values, label="Стоимость портфеля", linewidth=2)
        ax.plot(dates, invested, label="Внесено денег", linewidth=2, linestyle="--")
        ax.fill_between(dates, values, invested, where=[v >= i for v, i in zip(values, invested)], alpha=0.1, label="Прибыль")
        ax.fill_between(dates, values, invested, where=[v < i for v, i in zip(values, invested)], alpha=0.1, label="Убыток")
        ax.set_title("Долгосрочное инвестирование (купил и держи)", fontsize=12, fontweight="bold")
        ax.set_xlabel("Дата")
        ax.set_ylabel("Сумма, руб.")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis="x", rotation=45)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.0f}K"))

        self.figure.tight_layout()
        self.canvas.draw()

    def on_save(self):
        if self.current_result is None:
            return

        png_name = "portfolio_graph.png"
        self.figure.savefig(png_name, dpi=150, bbox_inches="tight")

        csv_name = "portfolio_data.csv"
        df = pandas.DataFrame({
            "Date": pandas.to_datetime(self.current_dates),
            "Value": self.current_result[:, 1],
            "Invested": self.current_result[:, 2]
        })
        df.to_csv(csv_name, index=False)

        self.statusbar.showMessage(f"Сохранено: {png_name} и {csv_name}")

    def on_clear(self):
        self.figure.clear()
        self.canvas.draw()

        self.current_result = None
        self.current_dates = None

        self.labelTotal.setText("Итоговая стоимость: 0 руб.")
        self.labelStatus.setText("Тикеры выбраны")
        self.btnSave.setEnabled(False)
        self.statusbar.showMessage("Очищено")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait()
        event.accept()