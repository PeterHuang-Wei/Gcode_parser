"""Minimal desktop GUI: open an .nc file, run it, see the toolpath.

A plain Tkinter window (stdlib, no new dependency) wrapping the same
simulator.run_file() + viz_matplotlib.plot_static()/animate() already
used by the CLI (cli.py) -- this is a second front end onto the same
engine, not a separate implementation. No web server, no browser.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox

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
        self._animation = None  # kept alive: FuncAnimation stops if garbage collected

        toolbar = tk.Frame(root)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        tk.Button(toolbar, text="Open .nc...", command=self.open_file).pack(side=tk.LEFT, padx=4, pady=4)
        self.run_button = tk.Button(toolbar, text="Run", command=self.run, state=tk.DISABLED)
        self.run_button.pack(side=tk.LEFT, padx=4, pady=4)

        self.animate_var = tk.BooleanVar(value=False)
        tk.Checkbutton(toolbar, text="Animate", variable=self.animate_var).pack(side=tk.LEFT, padx=4, pady=4)
        self.diameter_var = tk.BooleanVar(value=True)
        tk.Checkbutton(toolbar, text="X as diameter", variable=self.diameter_var).pack(side=tk.LEFT, padx=4, pady=4)

        self.path_label = tk.Label(toolbar, text="(no file open)", anchor="w", fg="gray30")
        self.path_label.pack(side=tk.LEFT, padx=8)

        self.status_label = tk.Label(root, text="", anchor="w", fg="gray20")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=2)

        self.figure = Figure(figsize=(7, 6))
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=root)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        NavigationToolbar2Tk(self.canvas, root).update()

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Open NC program", filetypes=[("NC programs", "*.nc"), ("All files", "*.*")]
        )
        if not path:
            return
        self.path = path
        self.path_label.config(text=path)
        self.run_button.config(state=tk.NORMAL)
        self.status_label.config(text="Loaded. Click Run to simulate.")

    def run(self) -> None:
        if not self.path:
            return
        self._animation = None
        self.ax.clear()
        try:
            toolpath = run_file(self.path)
        except (GcodeSimError, OSError) as exc:
            messagebox.showerror("Simulation error", str(exc))
            self.status_label.config(text=f"error: {exc}")
            return

        diameter = self.diameter_var.get()
        if self.animate_var.get():
            self._animation = animate(toolpath, diameter_programming=diameter, ax=self.ax)
        else:
            plot_static(toolpath, diameter_programming=diameter, ax=self.ax)
        self.canvas.draw()
        self.status_label.config(text=f"{len(toolpath.moves)} moves generated")


def main() -> None:
    root = tk.Tk()
    root.geometry("900x750")
    SimulatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
