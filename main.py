#!/usr/bin/env python3
"""
Калькулятор для Raspberry Pi OS с UI, похожим на калькулятор в macOS (режим «Обычный»).

Особенности:
- Окно на Tkinter (без внешних зависимостей, работает «из коробки» на Raspberry Pi OS).
- Макет 4x5 с кнопкой 0 шириной в две колонки, как у macOS.
- Цвета/контраст, близкие к macOS: серые функциональные, оранжевые операции, тёмный дисплей.
- Поддержка ввода с клавиатуры: 0-9, . , + - * /, Enter/Return (=), Esc (AC/C), Backspace (⌫).
- Логика, близкая к macOS: %, +/- (смена знака), C/AC, повторное =, форматирование вывода.
"""

import tkinter as tk
from tkinter import font as tkfont
import logging
from logging.handlers import RotatingFileHandler
import os


# ------------------ ЛОГИРОВАНИЕ ------------------
def _setup_logging():
    level_name = os.getenv("CALC_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logger = logging.getLogger("calculator")
    logger.setLevel(level)

    if logger.handlers:
        return logger  # уже настроен

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    # Консоль
    sh = logging.StreamHandler()
    sh.setLevel(level)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # Файл в каталоге приложения
    log_path = os.path.join(os.path.dirname(__file__), "calculator.log")
    fh = RotatingFileHandler(log_path, maxBytes=512_000, backupCount=2, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


log = _setup_logging()


class CalculatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Калькулятор")
        self.configure(bg="#1c1c1c")
        self.minsize(320, 480)

        # Состояние калькулятора
        self.reset_all()

        # Шрифты
        self.font_display = tkfont.Font(family="SF Pro Text", size=36, weight="bold")
        self.font_btn = tkfont.Font(family="SF Pro Text", size=16, weight="bold")

        # Виджеты
        self._build_ui()
        self._bind_keys()
        log.info("Приложение запущено")

    # ------------------ ЛОГИКА СОСТОЯНИЙ ------------------
    def reset_all(self):
        self.acc = 0.0  # аккумулятор (левая часть выражения)
        self.current = "0"  # текущий ввод (строка)
        self.operator = None  # '+', '-', '*', '/'
        self.last_operator = None  # для повторного '='
        self.last_operand = None
        self.just_evaluated = False
        self.awaiting_operand = False  # ждём ввод второго операнда после выбора оператора
        self.has_input = False  # для переключения AC/C
        log.debug("Сброс состояния (AC): acc=%.12g current=%s", self.acc, self.current)

    def _set_current(self, text: str):
        self.current = text
        self.has_input = (text != "0")
        self._update_display()
        log.debug("Текущий ввод установлен: %s", text)

    def _append_digit(self, d: str):
        if self.just_evaluated and self.operator is None:
            # Начинаем новое выражение после '='
            self.reset_all()
        self.just_evaluated = False
        if self.awaiting_operand:
            # После выбора оператора начинаем набор нового числа с нуля,
            # но на экране до ввода цифр остаётся предыдущее число
            self.current = "0"
            self.has_input = False
            self.awaiting_operand = False

        if self.current in ("-0", "0"):
            base = "-" if self.current.startswith("-") else ""
            self._set_current(base + d)
        else:
            self._set_current(self.current + d)
        log.debug("Нажата цифра: %s -> current=%s", d, self.current)

    def input_dot(self):
        if self.just_evaluated and self.operator is None:
            self.reset_all()
        self.just_evaluated = False
        if self.awaiting_operand:
            self.current = "0"
            self.has_input = False
            self.awaiting_operand = False

        if "." not in self.current:
            self._set_current(self.current + ".")
            log.debug("Добавлена точка: current=%s", self.current)
        else:
            log.debug("Игнорирована точка: уже есть в %s", self.current)

    def toggle_sign(self):
        if self.current.startswith("-"):
            self._set_current(self.current[1:])
        else:
            if self.current != "0":
                self._set_current("-" + self.current)
        log.debug("Смена знака: current=%s", self.current)

    def percent(self):
        try:
            cur = float(self.current.replace(",", "."))
        except ValueError:
            return
        if self.operator is None:
            # Просто делим на 100
            cur = cur / 100.0
        else:
            # Процент от аккумулятора (как в macOS)
            cur = self.acc * (cur / 100.0)
        formatted = self._format_number(cur)
        self._set_current(formatted)
        log.info("Процент: operator=%s acc=%s -> %s", self.operator, self.acc, formatted)

    def clear_entry_or_all(self):
        if self.has_input or self.just_evaluated:
            # C — очистка текущего ввода (не затрагивая аккумулятор/оператор)
            self._set_current("0")
            self.just_evaluated = False
            self.has_input = False
            # awaiting_operand не меняем: если ждали ввод — продолжаем ждать
            # last_operator/last_operand не трогаем
            self._update_display()
            log.info("Очистка ввода (C): текущий ввод сброшен")
        else:
            # AC — полный сброс
            # Требование: уже введённые цифры не должны исчезать с экрана.
            # Сохраняем отображаемый ввод, сбрасывая при этом внутреннее состояние.
            saved_current = self.current
            self.reset_all()
            # Восстанавливаем отображение, чтобы цифры не пропадали
            self.current = saved_current
            self.has_input = (self.current != "0")
            self._update_display()
            log.info("Полный сброс (AC)")

    def backspace(self):
        if self.just_evaluated:
            return
        s = self.current
        if len(s) <= 1 or (len(s) == 2 and s.startswith("-")):
            self._set_current("0")
        else:
            self._set_current(s[:-1])
        log.debug("Backspace -> current=%s", self.current)

    def set_operator(self, op: str):
        # Если только что было '=', продолжаем на результате
        if self.just_evaluated:
            self.just_evaluated = False

        try:
            cur = float(self.current)
        except ValueError:
            cur = 0.0

        if self.operator is None:
            # Начинаем новую операцию
            self.acc = cur
        else:
            # Сразу вычисляем цепочку операций (поведение macOS)
            self.acc = self._apply_operator(self.acc, cur, self.operator)
            # По требованию не изменяем отображение уже введённых цифр

        self.operator = op
        self.last_operator = None
        self.last_operand = None
        # По требованию: не очищаем введённые цифры на экране при выборе оператора
        # Но помечаем, что следующий ввод цифр должен начать новое число
        self.awaiting_operand = True
        log.info("Установка оператора: %s (acc=%s)", op, self.acc)
        # Немедленно обновляем дисплей, чтобы знак операции появился сразу после нажатия
        self._update_display()

    def equals(self):
        try:
            cur = float(self.current)
        except ValueError:
            cur = 0.0

        if self.operator is None:
            # Повторное '='
            if self.last_operator is not None and self.last_operand is not None:
                result = self._apply_operator(cur, self.last_operand, self.last_operator)
            else:
                result = cur
        else:
            result = self._apply_operator(self.acc, cur, self.operator)
            self.last_operator = self.operator
            self.last_operand = cur
            self.operator = None

        self._set_current(self._format_number(result))
        self.just_evaluated = True
        log.info("= нажато: результат=%s", self.current)

    def _apply_operator(self, a: float, b: float, op: str) -> float:
        try:
            if op == "+":
                res = a + b
                log.debug("Вычисление: %s + %s = %s", a, b, res)
                return res
            if op == "-":
                res = a - b
                log.debug("Вычисление: %s - %s = %s", a, b, res)
                return res
            if op == "*":
                res = a * b
                log.debug("Вычисление: %s * %s = %s", a, b, res)
                return res
            if op == "/":
                res = a / b
                log.debug("Вычисление: %s / %s = %s", a, b, res)
                return res
        except ZeroDivisionError:
            log.warning("Деление на ноль: %s / %s", a, b)
            return float("inf")
        return b

    # ------------------ UI ------------------
    def _build_ui(self):
        # Дисплей
        self.display_var = tk.StringVar()
        self.display = tk.Label(
            self,
            textvariable=self.display_var,
            anchor="e",
            bg="#1c1c1c",
            fg="white",
            padx=16,
            font=self.font_display
        )
        self.display.grid(row=0, column=0, columnspan=4, sticky="nsew")

        # Настройка сетки
        for i in range(1, 6):
            self.rowconfigure(i, weight=1, minsize=70)
        self.rowconfigure(0, weight=0, minsize=100)
        for j in range(4):
            self.columnconfigure(j, weight=1, minsize=80)

        # Цвета macOS-like
        color_fn = "#a5a5a5"   # светло-серые функциональные (AC, +/-, %)
        color_num = "#333333"  # тёмно-серые цифры
        color_op = "#ff9f0a"   # оранжевые операции
        color_op_active = "#c77800"

        def make_btn(text, r, c, w=1, color="#333333", cmd=None):
            # Создаём кнопку и оборачиваем команду, чтобы логировать НАТИСКАНИЕ любой кнопки
            btn = tk.Button(
                self, text=text, bg=color, fg="white",
                activebackground=color_op_active if color == color_op else "#4a4a4a",
                activeforeground="white", bd=0, font=self.font_btn
            )
            btn.grid(row=r, column=c, columnspan=w, sticky="nsew", padx=6, pady=6)
            def on_click(b=btn, c=cmd):
                try:
                    label = b.cget("text")
                except Exception:
                    label = "<btn>"
                log.info("Нажата кнопка: %s", label)
                if c:
                    c()
            btn.configure(command=on_click)
            return btn

        # Ряд функций: AC/C, +/-, % , /
        self.btn_ac = make_btn("AC", 1, 0, color=color_fn, cmd=self.clear_entry_or_all)
        make_btn("+/-", 1, 1, color=color_fn, cmd=self.toggle_sign)
        make_btn("%", 1, 2, color=color_fn, cmd=self.percent)
        make_btn("/", 1, 3, color=color_op, cmd=lambda: self.set_operator("/"))

        # Ряды цифр и операций
        make_btn("7", 2, 0, color=color_num, cmd=lambda: self._append_digit("7"))
        make_btn("8", 2, 1, color=color_num, cmd=lambda: self._append_digit("8"))
        make_btn("9", 2, 2, color=color_num, cmd=lambda: self._append_digit("9"))
        make_btn("*", 2, 3, color=color_op, cmd=lambda: self.set_operator("*"))

        make_btn("4", 3, 0, color=color_num, cmd=lambda: self._append_digit("4"))
        make_btn("5", 3, 1, color=color_num, cmd=lambda: self._append_digit("5"))
        make_btn("6", 3, 2, color=color_num, cmd=lambda: self._append_digit("6"))
        make_btn("-", 3, 3, color=color_op, cmd=lambda: self.set_operator("-"))

        make_btn("1", 4, 0, color=color_num, cmd=lambda: self._append_digit("1"))
        make_btn("2", 4, 1, color=color_num, cmd=lambda: self._append_digit("2"))
        make_btn("3", 4, 2, color=color_num, cmd=lambda: self._append_digit("3"))
        make_btn("+", 4, 3, color=color_op, cmd=lambda: self.set_operator("+"))

        make_btn("0", 5, 0, w=2, color=color_num, cmd=lambda: self._append_digit("0"))
        make_btn(".", 5, 2, color=color_num, cmd=self.input_dot)
        make_btn("=", 5, 3, color=color_op, cmd=self.equals)

        self._update_display()

    def _bind_keys(self):
        # Хелпер для биндов с логированием нажатий клавиш
        def bind_with_log(sequence: str, func, label: str = None):
            def handler(_e, f=func, lab=(label or sequence)):
                log.info("Нажата клавиша: %s", lab)
                f()
            self.bind(sequence, handler)

        # Цифры
        for d in "0123456789":
            bind_with_log(d, lambda x=d: self._append_digit(x), label=d)
        # Точка и запятая
        bind_with_log(".", lambda: self.input_dot(), label=".")
        bind_with_log(",", lambda: self.input_dot(), label=",")
        # Операции
        for sym in ["+", "-", "*", "/"]:
            bind_with_log(sym, lambda x=sym: self.set_operator(x), label=sym)
        # Равно / Enter
        bind_with_log("=", lambda: self.equals(), label="=")
        bind_with_log("<Return>", lambda: self.equals(), label="Enter")
        # AC/C
        bind_with_log("<Escape>", lambda: self.clear_entry_or_all(), label="Esc")
        # Backspace
        bind_with_log("<BackSpace>", lambda: self.backspace(), label="Backspace")

    # ------------------ ОТОБРАЖЕНИЕ ------------------
    def _format_number(self, value: float) -> str:
        if value == float("inf") or value != value:  # inf или NaN
            return "Ошибка"
        # Ограничим по разрядности дисплея
        # Сначала пробуем без экспоненты
        s = ("%0.12g" % value)
        # Заменим возможную экспоненту на более компактный вариант
        # и приведём к обычному виду, где это разумно
        if "e" in s or "E" in s:
            try:
                s = ("%0.12f" % value).rstrip("0").rstrip(".")
            except Exception:
                pass
        # Уберём лишние нули после запятой
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        # Если строка слишком длинная, переключимся на экспоненту
        if len(s) > 12:
            s = ("%0.6e" % value)
        return s

    def _update_display(self):
        # Меняем текст кнопки AC/C
        self.btn_ac.config(text="C" if (self.has_input or self.just_evaluated) else "AC")
        # Обновляем дисплей
        text = self.current
        # Если произошла ошибка — показываем только её
        if text == "Ошибка":
            shown = text
        else:
            # Отрисовываем выражение с оператором, если он есть
            if self.operator is not None:
                # Форматируем левый операнд (аккумулятор)
                try:
                    left = self._format_number(float(self.acc))
                except Exception:
                    left = str(self.acc)

                if self.awaiting_operand:
                    # Оператор выбран, ожидаем ввод второго операнда: «левый op»
                    shown = f"{left} {self.operator}"
                else:
                    # Идёт ввод второго операнда: «левый op правый»
                    try:
                        right = self._format_number(float(text))
                    except ValueError:
                        right = text
                    shown = f"{left} {self.operator} {right}"
            else:
                # Оператора нет — показываем текущее число
                try:
                    shown = self._format_number(float(text))
                except ValueError:
                    shown = text
        self.display_var.set(shown)
        log.debug("Обновление дисплея: %s", shown)


def main():
    try:
        app = CalculatorApp()
        app.mainloop()
    finally:
        log.info("Приложение завершено")


if __name__ == "__main__":
    main()
