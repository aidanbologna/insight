import tkinter as tk
import yfinance as yf
from tkinter import ttk
from PIL import Image, ImageTk
from datetime import datetime
import pandas as pd
from urllib import request
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

# 1. Create the main application window
root = tk.Tk()
root.title("Insight by Milton")
root.geometry("800x600")  # Width x Height in pixels

# Allow column 0 to expand and fill the extra window width
root.columnconfigure(0, weight=1)

# 3. The stock plotting function — redraws the SAME chart
def fetch_and_plot_stock_data():
    query = search_entry.get().strip().upper()
    if not query:
        query = "AAPL"  # default if the box is empty
    try:
        stock = yf.download(query, start="2026-01-01",
                            end=datetime.now().strftime("%Y-%m-%d"))

        if stock.empty:
            print(f"No data found for '{query}'. Check the ticker symbol.")
            return

        if isinstance(stock.columns, pd.MultiIndex):
            stock.columns = stock.columns.get_level_values(0)

        stock["returns"] = stock["Close"].pct_change()

        ax.clear()
        ax.plot(stock.index, stock["Close"], color="steelblue", linewidth=1.5)
        ax.set_title(f"{query} — Current Price: ${stock['Close'].iloc[-1]:.2f}", fontsize=14)
        ax.set_xlabel("Date")
        ax.set_ylabel("Price per Share ($)")
        fig.tight_layout()

        canvas.draw()
        toolbar.update()
    except Exception as e:
        print(f"Error fetching or plotting data: {e}")

# 4. Search bar (row 3)
search_frame = tk.Frame(root)
search_frame.grid(row=3, column=0, sticky="e", padx=10, pady=5)
search_entry = tk.Entry(search_frame, width=30)
search_entry.pack(side="left", padx=5)
search_entry.bind("<Return>", lambda event: fetch_and_plot_stock_data())
search_button = tk.Button(search_frame, text="Search", command=fetch_and_plot_stock_data)
search_button.pack(side="left", padx=5)

# 5. Build the figure / canvas / toolbar ONCE (row 4 = chart, row 5 = toolbar)
fig = Figure(figsize=(12, 5))
ax = fig.add_subplot(111)

canvas = FigureCanvasTkAgg(fig, master=root)
canvas_widget = canvas.get_tk_widget()
canvas_widget.grid(row=4, column=0, sticky="nsew", padx=10, pady=10)
root.rowconfigure(4, weight=1)  # chart grows vertically when the window resizes
canvas.draw()

# Toolbar in its own frame (NavigationToolbar2Tk packs itself internally)
toolbar_frame = tk.Frame(root)
toolbar_frame.grid(row=5, column=0, sticky="ew", padx=10)
toolbar = NavigationToolbar2Tk(canvas, toolbar_frame)
toolbar.update()

# NOTE: this is defined here (before the Bond Market button) because command=
# needs the name to exist when the button is built. It references ax/fig/canvas/
# toolbar, which are created lower down — fine, because the body only runs on click.
def currentYieldCurve():
    """Fetch the latest Treasury yields and draw the yield curve on the shared chart."""
    try:
        padded_month = datetime.now().strftime("%m")
        current_year = datetime.now().strftime("%Y")
        url = (
            f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
            f"daily-treasury-rates.csv/all/{current_year}{padded_month}"
            f"?type=daily_treasury_yield_curve"
            f"&field_tdr_date_value_month={current_year}{padded_month}&page&_format=csv"
        )
        csv_path = "C:/Users/Owner/OneDrive/Desktop/daily-treasury-rates.csv"
        #request.urlretrieve(url, csv_path)

        df = pd.read_csv(csv_path)
        df["Date"] = pd.to_datetime(df["Date"])
        latest_row = df.sort_values("Date").iloc[-1]  # most recent trading day

        # Recession signal checks (printed to the console)
        if float(latest_row["2 Yr"]) > float(latest_row["10 Yr"]):
            print("Inverted yield curve (2yr vs 10yr) - potential recession signal")
        else:
            print("Normal yield curve (2yr vs 10yr) - no immediate signal")
        if float(latest_row["3 Mo"]) > float(latest_row["10 Yr"]):
            print("Inverted yield curve (3mo vs 10yr) - potential recession signal")
        else:
            print("Normal yield curve (3mo vs 10yr) - no immediate signal")

        # Build the (maturity, yield) points
        maturity_mapping = {
            "1 Yr": 1.0,
            "2 Yr": 2.0,
            "3 Yr": 3.0,
            "10 Yr": 10.0,
            "20 Yr": 20.0,
            "30 Yr": 30.0,
        }
        x_years, y_yields = [], []
        for name, years in maturity_mapping.items():
            if name in latest_row:
                x_years.append(years)
                y_yields.append(float(latest_row[name]))

        # Redraw onto the SHARED ax — same pattern as the stock function
        ax.clear()
        ax.plot(x_years, y_yields, marker="o", linestyle="-", color="b", linewidth=2)
        ax.set_title(f"U.S. Treasury Yield Curve ({latest_row['Date'].strftime('%Y-%m-%d')})")
        ax.set_xlabel("Maturity (Years)")
        ax.set_ylabel("Yield (%)")
        ax.set_xticks(list(maturity_mapping.values()))
        ax.set_xticklabels(list(maturity_mapping.keys()), rotation=45)
        ax.grid(True, linestyle="--", alpha=0.6)
        fig.tight_layout()

        canvas.draw()     # repaint the existing canvas
        toolbar.update()  # reset the toolbar history to the new chart
    except Exception as e:
        print(f"Error fetching or plotting yield curve: {e}")

# Set icon
app_icon = tk.PhotoImage(file="C:/Users/Owner/OneDrive/Desktop/insight/assets/icon.png")
root.iconphoto(False, app_icon)

# Load and resize the logo
upperWindowImageLink = Image.open("C:/Users/Owner/OneDrive/Desktop/insight/assets/logo.png")
resized_image = upperWindowImageLink.resize((200, 50))
upperWindowImage = ImageTk.PhotoImage(resized_image)

# Header frame
header = tk.Frame(root)
header.grid(row=0, column=0, sticky="ew", padx=10, pady=5)
header.columnconfigure(0, weight=1, uniform="sides")  # left spacer
header.columnconfigure(2, weight=1, uniform="sides")  # right spacer

# Logo on the far left (column 0)
upperWindowImageLabel = tk.Label(header, image=upperWindowImage)
upperWindowImageLabel.grid(row=0, column=0, sticky="w")

# Buttons in the middle column (column 1) — lands dead center
button_frame = tk.Frame(header)
button_frame.grid(row=0, column=1)

tk.Button(button_frame, text="Home").pack(side="left", padx=5)
tk.Button(button_frame, text="Markets", command=fetch_and_plot_stock_data).pack(side="left", padx=5)
tk.Button(button_frame, text="News").pack(side="left", padx=5)
tk.Button(button_frame, text="Watchlist").pack(side="left", padx=5)
tk.Button(button_frame, text="Bond Market", command=currentYieldCurve).pack(side="left", padx=5)

# Separator under the header
separator = ttk.Separator(root, orient="horizontal")
separator.grid(row=1, column=0, sticky="ew", pady=5)

# 2. Date/time label (row 2)
label = tk.Label(root, text="Current Date and Time: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"), font=("Arial", 14))

def Update():
    now = datetime.now()
    label.config(text="Current Date and Time: " + now.strftime("%Y-%m-%d %H:%M:%S"))
    root.after(1000, Update)

label.grid(row=2, column=0, pady=10)
Update()  # start the clock loop

# 6. Draw the initial chart (AAPL by default) so the window isn't empty on launch
fetch_and_plot_stock_data()

# Try importing the pyi_splash module, which only exists inside the compiled EXE
try:
    import pyi_splash
    pyi_splash.close()
except ImportError:
    pass

root.mainloop()