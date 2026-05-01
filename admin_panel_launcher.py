import sys
import webbrowser
from tkinter import Tk, Label, Button, Frame

ADMIN_URL = "https://paymentapproval.onrender.com/login"
REPORTS_URL = "https://paymentapproval.onrender.com/reports"


def open_admin() -> None:
    webbrowser.open_new(ADMIN_URL)


def open_reports() -> None:
    webbrowser.open_new(REPORTS_URL)


def build_ui() -> Tk:
    root = Tk()
    root.title("EMD Admin Panel Launcher")
    root.geometry("440x220")
    root.resizable(False, False)

    Label(
        root,
        text="EMD Purchase - Admin Panel",
        font=("Segoe UI", 14, "bold"),
        pady=16,
    ).pack()

    Label(
        root,
        text="Open the hosted admin portal in your browser.",
        font=("Segoe UI", 10),
    ).pack(pady=(0, 12))

    row = Frame(root)
    row.pack(pady=8)

    Button(
        row,
        text="Open Admin Panel",
        width=18,
        command=open_admin,
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=0, padx=6)

    Button(
        row,
        text="Open Reports",
        width=14,
        command=open_reports,
        font=("Segoe UI", 10),
    ).grid(row=0, column=1, padx=6)

    Button(
        root,
        text="Exit",
        width=10,
        command=root.destroy,
        font=("Segoe UI", 10),
    ).pack(pady=16)

    return root


def main() -> int:
    app = build_ui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
