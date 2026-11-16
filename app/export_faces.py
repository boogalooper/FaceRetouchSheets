"""Collect photos for face retouching, with a GUI or command line."""
import argparse
import json
import os
import queue
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from detector import MODEL_NAME, find_default_model, load_detector
from retouch_sheets import (
    DEFAULT_SHEET_FORMAT, LIMIT, NECK_MARGIN, SHEET_FORMATS, RetouchOptions,
    export_retouch, validate_destination, validate_sheet_size,
)

DEVICES = {"Авто": "auto", "GPU (CUDA)": "gpu", "CPU": "cpu"}


def settings_path():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FaceRetouchSheets" / "settings.json"


def load_settings():
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def apply_defaults(args, saved):
    folder = saved.get("folder")
    if args.folder is None and isinstance(folder, str):
        args.folder = folder
    for name, allowed, default in (("device", DEVICES.values(), "auto"), ("format", SHEET_FORMATS, DEFAULT_SHEET_FORMAT)):
        if getattr(args, name) is None:
            value = saved.get(name)
            setattr(args, name, value if value in allowed else default)
    if args.neck is None:
        value = saved.get("neck")
        args.neck = value if type(value) in (int, float) and 0 <= value <= 3 else NECK_MARGIN
    for name in ("max_width", "max_height"):
        if getattr(args, name) is None:
            value = saved.get(name)
            setattr(args, name, value if type(value) is int and 1 <= value <= LIMIT else LIMIT)



def save_settings(values):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            pending = Path(file.name)
            file.write(json.dumps(values, ensure_ascii=False, indent=2) + "\n")
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


class Cancelled(RuntimeError):
    pass


def run_batch(root, model, image_format, neck, device, progress, check_cancel, log,
              *, max_width=LIMIT, max_height=LIMIT):
    validate_destination(root)
    validate_sheet_size(max_width, max_height)
    if model is None or not model.is_file() or model.suffix.lower() != ".onnx":
        raise ValueError(f"Не найден детектор models/{MODEL_NAME}. Запустите install.bat для установки модели.")
    if not 0 <= neck <= 3:
        raise ValueError("Запас под шею должен быть от 0 до 3 высот лица.")
    check_cancel()
    progress(0, 0, "Загрузка детектора…")
    detector = load_detector(model, device, log)
    check_cancel()
    return export_retouch(root, RetouchOptions(image_format, neck, max_width, max_height),
                          detector, progress, check_cancel, log)


def describe(result):
    return (f"Фото: {result.photos} · лиц: {result.patches} · листов: {result.sheets}\n"
            f"Без лиц: {result.no_faces} · с пересечениями: {result.overlaps} · ошибок: {result.errors}\n"
            f"{result.destination}")


class RetouchApp(tk.Tk):
    def __init__(self, args):
        super().__init__()
        self.title("Листы для ретуши")
        self.photos = tk.StringVar(value=args.folder or "")
        self.model = args.model.expanduser() if args.model is not None else None
        self.image_format = tk.StringVar(value=args.format)
        self.neck = tk.StringVar(value=str(args.neck))
        self.max_width = tk.StringVar(value=str(args.max_width))
        self.max_height = tk.StringVar(value=str(args.max_height))
        self.device = tk.StringVar(value=next(label for label, value in DEVICES.items() if args.device == value))
        self.status = tk.StringVar(value="Выберите папку съёмки.")
        self.provider = tk.StringVar()
        self.events = queue.Queue()
        self.cancellation = threading.Event()
        self.worker = None
        self.closing = False
        self.result = None
        self.controls = []

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        self.path_row(frame, 0, "Папка съёмки", self.photos, filedialog.askdirectory)
        settings = ttk.Frame(frame)
        settings.grid(row=1, column=0, columnspan=3, sticky="w", pady=12)
        for label, variable, values in (("Формат", self.image_format, SHEET_FORMATS),
                                        ("Устройство", self.device, tuple(DEVICES))):
            ttk.Label(settings, text=label).pack(side="left", padx=(0, 6))
            field = ttk.Combobox(settings, textvariable=variable, values=values, width=13, state="readonly")
            field.pack(side="left", padx=(0, 14))
            self.controls.append(field)
        ttk.Label(settings, text="Запас под шею").pack(side="left", padx=(0, 6))
        neck = ttk.Entry(settings, textvariable=self.neck, width=6)
        neck.pack(side="left")
        self.controls.append(neck)

        sizes = ttk.Frame(frame)
        sizes.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Label(sizes, text="Макс. размер листа").pack(side="left", padx=(0, 6))
        width = ttk.Entry(sizes, textvariable=self.max_width, width=7)
        width.pack(side="left")
        ttk.Label(sizes, text="×").pack(side="left", padx=5)
        height = ttk.Entry(sizes, textvariable=self.max_height, width=7)
        height.pack(side="left")
        ttk.Label(sizes, text="px (ширина × высота)").pack(side="left", padx=(6, 0))
        self.controls.extend((width, height))

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky="ew")
        self.start_button = ttk.Button(buttons, text="Собрать листы", command=self.start_export)
        self.start_button.pack(side="left")
        self.controls.append(self.start_button)
        self.cancel_button = ttk.Button(buttons, text="Отмена", command=self.cancel_export, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.result_button = ttk.Button(buttons, text="Открыть результат", command=self.open_result, state="disabled")
        self.result_button.pack(side="right")

        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(16, 6))
        self.update_idletasks()
        text_width = max(settings.winfo_reqwidth(), sizes.winfo_reqwidth(), buttons.winfo_reqwidth())
        ttk.Label(frame, textvariable=self.provider, wraplength=text_width).grid(
            row=5, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, textvariable=self.status, wraplength=text_width).grid(
            row=6, column=0, columnspan=3, sticky="w")
        self.protocol("WM_DELETE_WINDOW", self.close_window)
        self.bind("<Escape>", lambda _: self.cancel_export())
        self.after(80, self.poll_events)

    def path_row(self, frame, index, label, variable, browse):
        def select():
            selected = browse()
            if selected:
                variable.set(selected)

        ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", padx=(0, 12), pady=4)
        entry = ttk.Entry(frame, textvariable=variable)
        entry.grid(row=index, column=1, sticky="ew", pady=4)
        button = ttk.Button(frame, text="Обзор…", command=select)
        button.grid(row=index, column=2, padx=(8, 0), pady=4)
        self.controls.extend((entry, button))

    def remember_settings(self):
        saved = load_settings()
        saved.update(folder=self.photos.get().strip(), format=self.image_format.get(),
                     device=DEVICES[self.device.get()])
        try:
            neck = float(self.neck.get().replace(",", "."))
            if 0 <= neck <= 3:
                saved["neck"] = neck
        except ValueError:
            pass
        for name in ("max_width", "max_height"):
            try:
                value = int(getattr(self, name).get())
                if 1 <= value <= LIMIT:
                    saved[name] = value
            except ValueError:
                pass
        try:
            save_settings(saved)
        except OSError as exc:
            print(f"Не удалось сохранить настройки: {exc}", file=sys.stderr)

    def start_export(self):
        if self.worker is not None:
            return
        try:
            if not self.photos.get().strip():
                raise ValueError("Укажите папку съёмки.")
            root = Path(self.photos.get().strip()).expanduser().resolve()
            model = self.model
            neck = float(self.neck.get().replace(",", "."))
            image_format = self.image_format.get()
            device = DEVICES[self.device.get()]
            try:
                max_width, max_height = int(self.max_width.get()), int(self.max_height.get())
            except ValueError as exc:
                raise ValueError("Введите целые числа для ширины и высоты листа.") from exc
            validate_sheet_size(max_width, max_height)
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror(self.title(), str(exc), parent=self)
            return

        def check_cancel():
            if self.cancellation.is_set():
                raise Cancelled("Экспорт отменён.")

        def task():
            try:
                result = run_batch(root, model, image_format, neck, device,
                                   lambda *data: self.events.put(("progress", data)), check_cancel,
                                   lambda text: self.events.put(("log", text)),
                                   max_width=max_width, max_height=max_height)
                self.events.put(("done", result))
            except Cancelled as exc:
                self.events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        self.remember_settings()
        self.cancellation.clear()
        self.provider.set("")
        self.result = None
        self.result_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])
        for control in self.controls:
            control.state(["disabled"])
        self.worker = threading.Thread(target=task, daemon=True)
        self.worker.start()

    def cancel_export(self):
        if self.worker is not None:
            self.cancellation.set()
            self.cancel_button.state(["disabled"])
            self.status.set("Отмена…")

    def close_window(self):
        self.remember_settings()
        if self.worker is None:
            self.destroy()
        else:
            self.closing = True
            self.cancel_export()

    def poll_events(self):
        try:
            for _ in range(100):
                kind, data = self.events.get_nowait()
                if kind == "progress":
                    done, total, label = data
                    if total:
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=100 * done / total)
                    elif str(self.progress.cget("mode")) != "indeterminate":
                        self.progress.configure(mode="indeterminate")
                        self.progress.start(12)
                    if not self.cancellation.is_set():
                        self.status.set(label)
                elif kind == "log":
                    if data.startswith(("Детектор SCRFD:", "CUDA недоступна")):
                        self.provider.set(data)
                else:
                    self.worker = None
                    if self.closing:
                        self.destroy()
                        return
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=100 if kind == "done" else 0)
                    self.cancel_button.state(["disabled"])
                    for control in self.controls:
                        control.state(["!disabled"])
                    if kind == "done":
                        self.result = data.destination
                        self.status.set(describe(data))
                        self.result_button.state(["!disabled"])
                    else:
                        self.status.set(data)
                        if kind == "error":
                            messagebox.showerror(self.title(), data, parent=self)
        except queue.Empty:
            pass
        self.after(80, self.poll_events)

    def open_result(self):
        if self.result is not None:
            try:
                os.startfile(str(self.result))
            except OSError as exc:
                messagebox.showerror(self.title(), str(exc), parent=self)


def main():
    # pythonw has no console streams; native model wrappers may still print.
    if sys.stdout is None or sys.stderr is None:
        log_path = settings_path().parent / "runtime.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", help="папка фотографий")
    parser.add_argument("--model", type=Path, default=find_default_model())
    parser.add_argument("--device", choices=("auto", "gpu", "cpu"))
    parser.add_argument("--format", choices=SHEET_FORMATS)
    parser.add_argument("--neck", type=float)
    parser.add_argument("--max-width", type=int, help="максимальная ширина листа в px")
    parser.add_argument("--max-height", type=int, help="максимальная высота листа в px")
    parser.add_argument("--cli", action="store_true", help="экспорт без окна")
    args = parser.parse_args()
    apply_defaults(args, {} if args.cli else load_settings())
    if not args.cli:
        RetouchApp(args).mainloop()
        return 0
    if not args.folder or not args.model:
        parser.error("Для --cli укажите папку фотографий и модель через --model.")
    try:
        result = run_batch(Path(args.folder).expanduser().resolve(), args.model.expanduser(), args.format,
                           args.neck, args.device, lambda done, total, label: print(
                               f"[{done}/{total}] {label}" if total else label, flush=True),
                           lambda: None, lambda text: print(text, flush=True),
                           max_width=args.max_width, max_height=args.max_height)
    except KeyboardInterrupt:
        print("Экспорт отменён.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(describe(result))
    return 2 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())
