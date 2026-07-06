"""Minimal desktop GUI: open an .nc file, run it, see the toolpath.

A plain Tkinter window (stdlib, no new dependency) wrapping the same
simulator.run_file() + viz_matplotlib.plot_static()/animate() already
used by the CLI (cli.py) -- this is a second front end onto the same
engine, not a separate implementation. No web server, no browser.
"""

from __future__ import annotations

import tkinter as tk
import warnings
from tkinter import filedialog, messagebox, scrolledtext

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from .errors import GcodeSimError  # noqa: E402
from .simulator import run_file  # noqa: E402
from .viz_matplotlib import animate, plot_static  # noqa: E402


class SimulatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("G-code Simulator")
        self.path: str | None = None
        self.ignore_path: str | None = None
        self._animation = None  # kept alive: FuncAnimation stops if garbage collected

        toolbar = tk.Frame(root)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(toolbar, text="Open .nc...", command=self.open_file).pack(side=tk.LEFT, padx=4, pady=4)
        self.run_button = tk.Button(toolbar, text="Run", command=self.run, state=tk.DISABLED)
        self.run_button.pack(side=tk.LEFT, padx=4, pady=4)
        tk.Button(toolbar, text="Ignore list...", command=self.open_ignore_file).pack(side=tk.LEFT, padx=4, pady=4)

        self.animate_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar, text="Animate", variable=self.animate_var).pack(side=tk.LEFT, padx=4, pady=4)
        self.diameter_var = tk.BooleanVar(value=True)
        tk.Checkbutton(toolbar, text="X as diameter", variable=self.diameter_var).pack(side=tk.LEFT, padx=4, pady=4)

        self.path_label = tk.Label(toolbar, text="(no file open)", anchor="w", fg="gray30")
        self.path_label.pack(side=tk.LEFT, padx=8)

        self.status_label = tk.Label(root, text="", anchor="w", fg="gray20")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=2)

        # Left: the loaded program's raw source text (read-only). Right:
        # the plotted toolpath. A PanedWindow lets the user resize either
        # side to see more code or more of the plot.
        body = tk.PanedWindow(root, orient=tk.HORIZONTAL, sashwidth=4)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        code_frame = tk.Frame(body)
        tk.Label(code_frame, text="Loaded program", anchor="w", fg="gray30").pack(side=tk.TOP, fill=tk.X)
        self.code_text = scrolledtext.ScrolledText(code_frame, wrap=tk.NONE, width=48, font=("Courier", 10))
        self.code_text.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.code_text.configure(state=tk.DISABLED)
        body.add(code_frame, minsize=200)

        plot_frame = tk.Frame(body)
        self.figure = Figure(figsize=(7, 6))
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, plot_frame).update()
        body.add(plot_frame, minsize=300)

        # Warnings raised during a run (e.g. an unrecognized G-code/macro
        # variable alias that got skipped) go to Python's warnings module,
        # which by default only prints to stderr -- easy to miss entirely
        # in a windowed app with no visible console, and the single most
        # likely reason a run silently produces an empty/wrong-looking
        # toolpath with no obvious cause. Shown here instead so the
        # "why" is never just invisible.
        warnings_frame = tk.Frame(root)
        warnings_frame.pack(side=tk.TOP, fill=tk.X)
        tk.Label(warnings_frame, text="Warnings from last run", anchor="w", fg="gray30").pack(
            side=tk.TOP, fill=tk.X
        )
        self.warnings_text = scrolledtext.ScrolledText(warnings_frame, height=5, wrap=tk.WORD, fg="darkorange4")
        self.warnings_text.pack(side=tk.TOP, fill=tk.X)
        self.warnings_text.configure(state=tk.DISABLED)

    def _show_code(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                source = f.read()
        except OSError as exc:
            source = f"(could not read file for display: {exc})"
        self.code_text.configure(state=tk.NORMAL)
        self.code_text.delete("1.0", tk.END)
        self.code_text.insert(tk.END, source)
        self.code_text.configure(state=tk.DISABLED)

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open NC program",
            # Windows/macOS dialogs match extensions case-insensitively;
            # Linux (GTK) ones can be case-sensitive, so both cases are
            # listed explicitly to make sure ".CNC"/".TXT" (as well as
            # the lowercase forms) show up on every platform.
            filetypes=[
                ("NC programs", "*.nc *.NC *.cnc *.CNC *.txt *.TXT"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        self.path = path
        self.path_label.config(text=path)
        self.run_button.config(state=tk.NORMAL)
        self.status_label.config(text="Loaded. Click Run to simulate.")
        self._show_code(path)

    def open_ignore_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open ignore-list file (one 'G<n>' or '#<n>' per line)",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        self.ignore_path = path
        self.status_label.config(text=f"Ignore list: {path}")

    def _set_warnings_text(self, lines: list[str]) -> None:
        self.warnings_text.configure(state=tk.NORMAL)
        self.warnings_text.delete("1.0", tk.END)
        self.warnings_text.insert(tk.END, "\n".join(lines) if lines else "(none)")
        self.warnings_text.configure(state=tk.DISABLED)

    def run(self) -> None:
        if not self.path:
            return
        self._animation = None
        self.ax.clear()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                toolpath = run_file(self.path, ignore_config_path=self.ignore_path)
        except (GcodeSimError, OSError) as exc:
            messagebox.showerror("Simulation error", str(exc))
            self.status_label.config(text=f"error: {exc}")
            return

        warning_lines = [str(w.message) for w in caught]
        self._set_warnings_text(warning_lines)

        diameter = self.diameter_var.get()
        if self.animate_var.get():
            self._animation = animate(toolpath, diameter_programming=diameter, ax=self.ax)
        else:
            plot_static(toolpath, diameter_programming=diameter, ax=self.ax)
        self.canvas.draw()

        status = f"{len(toolpath.moves)} moves generated"
        if warning_lines:
            status += f" -- {len(warning_lines)} warning(s), see panel below"
        if not toolpath.moves:
            status += " -- toolpath is EMPTY; check the warnings panel and loaded code for why"
        self.status_label.config(text=status)


def main() -> None:
    root = tk.Tk()
    root.geometry("900x750")
    SimulatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
