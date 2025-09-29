# %%
import datetime as dt
import time
import statistics 
import logging
import numpy as np
import math
from optibook.synchronous_client import Exchange
import os
import sys

exchange = Exchange()
exchange.connect()

logging.getLogger("client").setLevel("ERROR")

# ========== Utility Functions ==========

def year_fraction(date):
    start = dt.date(date.year, 1, 1).toordinal()
    year_length = dt.date(date.year+1, 1, 1).toordinal() - start
    return date.year + float(date.toordinal() - start) / year_length

def get_futures_of_stock(stock_name):
    instruments = exchange.get_instruments()
    stock_futures = {}
    for instrument_name in instruments:
        parts = instrument_name.split("_")
        if (parts[0] == stock_name) and (parts[-1] == "F"):
            stock_futures[instrument_name] = instruments[instrument_name]
    return stock_futures

def get_future_book_discount(future_id):
    future = exchange.get_instruments()[future_id]
    interest_rate = future.interest_rate
    maturity = future.expiry
    current_date = dt.datetime.now()
    tau = year_fraction(maturity) - year_fraction(current_date)
    discount_factor = np.exp(interest_rate * tau)
    return discount_factor

def trade_would_breach_position_limit(instrument_id, volume, side, position_limit=100):
    positions = exchange.get_positions()
    position = positions[instrument_id]
    if side == "bid":
        return position + volume > position_limit
    elif side == "ask":
        return position - volume < -position_limit
    else:
        raise Exception(f"Invalid side: {side}")

def trade_would_breach_position_limit_future(instrument_id, volume, side, discount_factor, position_limit=100):
    positions = exchange.get_positions()
    position = positions[instrument_id] * discount_factor
    if side == "bid":
        return position + volume > position_limit
    elif side == "ask":
        return position - volume < -position_limit
    else:
        raise Exception(f"Invalid side: {side}")

def print_positions_and_pnl(always_display=None):
    positions = exchange.get_positions()
    print("Positions:")
    for instrument_id in positions:
        if not always_display or instrument_id in always_display or positions[instrument_id] != 0:
            print(f"  {instrument_id:20s}: {positions[instrument_id]:4.0f}")
    pnl = exchange.get_pnl()
    if pnl:
        print(f"\nPnL: {pnl:.2f}")

# ========== Core Trading Functions ==========

def max_volume_hedged(stock_id, stock_id_future, operation_future, volume_future, volume_stock, discount_factor, stock_limit=100, future_limit=100):
    positions = exchange.get_positions()
    pos_stock = positions[stock_id]
    pos_future = positions[stock_id_future]

    if operation_future == "ask":
        max_future_sell = future_limit + pos_future
        max_stock_buy = stock_limit - pos_stock
        volume_stock_hedged = min(max_stock_buy, max_future_sell * discount_factor, volume_future * discount_factor, volume_stock)
        volume_future_hedged = volume_stock_hedged / discount_factor
    elif operation_future == "bid":
        max_future_buy = future_limit - pos_future
        max_stock_sell = stock_limit + pos_stock
        volume_stock_hedged = min(max_stock_sell, max_future_buy * discount_factor, volume_future * discount_factor, volume_stock)
        volume_future_hedged = volume_stock_hedged / discount_factor
    else:
        return 0, 0

    return math.floor(volume_future_hedged), math.floor(volume_stock_hedged)

def trade_pair_future(stock_id, stock_id_future, discount_factor):
    stock_book = exchange.get_last_price_book(stock_id)
    future_book = exchange.get_last_price_book(stock_id_future)

    if not (stock_book and stock_book.bids and stock_book.asks):
        print(f"Stock {stock_id} book incomplete. Skipping.")
        return "none", 0

    best_bid = stock_book.bids[0].price
    best_ask = stock_book.asks[0].price

    side = "none"

    if future_book.asks:
        ask_future = future_book.asks[0].price
        if ask_future < best_bid * discount_factor + 0.05:
            side = "bid"
            price_future = ask_future
            volume_stock = stock_book.bids[0].volume
            volume_future = future_book.asks[0].volume

    if future_book.bids:
        bid_future = future_book.bids[0].price
        if bid_future > best_ask * discount_factor + 0.05:
            side = "ask"
            price_future = bid_future
            volume_stock = stock_book.asks[0].volume
            volume_future = future_book.bids[0].volume

    if side != "none":
        future_vol, stock_vol = max_volume_hedged(
            stock_id, stock_id_future, side, volume_future, volume_stock, discount_factor
        )
        if future_vol > 0:
            exchange.insert_order(
                instrument_id=stock_id_future,
                price=price_future,
                volume=future_vol,
                side=side,
                order_type="ioc",
            )
        return side, future_vol
    return "none", 0

def hedge_pair_future(stock_id, stock_id_future, discount_factor, trade_side):
    positions = exchange.get_positions()
    if trade_side == "bid":
        trade_adjustment = 1
    elif trade_side == "ask":
        trade_adjustment = -1
    else:
        trade_adjustment = 0

    outstanding_position = round(positions[stock_id] + positions[stock_id_future] * discount_factor + trade_adjustment)

    if outstanding_position > 0:
        stock_book = exchange.get_last_price_book(stock_id)
        if not (stock_book and stock_book.bids):
            print(f"{stock_id} has no bids. Skipping hedge.")
            return 0
        price = stock_book.bids[0].price
        side = "ask"
        volume = outstanding_position
    elif outstanding_position < 0:
        stock_book = exchange.get_last_price_book(stock_id)
        if not (stock_book and stock_book.asks):
            print(f"{stock_id} has no asks. Skipping hedge.")
            return 0
        price = stock_book.asks[0].price
        side = "bid"
        volume = -outstanding_position
    else:
        return 0

    if not trade_would_breach_position_limit(stock_id, volume, side):
        exchange.insert_order(
            instrument_id=stock_id,
            price=price,
            volume=volume,
            side=side,
            order_type="ioc",
        )
        print(f"Inserting {side} for {stock_id}: {volume} @ {price:.2f}")
        return volume
    return False

# ========== Get Stocks List ==========

def get_stocks():
    instruments = exchange.get_instruments()
    return [name for name in instruments if "_" not in name]

# ========== Main ==========

if __name__ == "__main__":
    pnl_totals = []
    traded_volume = 0
    trade_count = 0

    STOCKS = get_stocks()
    FUTURES = [(stock, list(get_futures_of_stock(stock).keys())[-1]) for stock in STOCKS if get_futures_of_stock(stock)]

    start_time = time.time()
    max_duration = 30 * 60  # 30 mins

    while True:
        if time.time() - start_time >= max_duration:
            print("30 minutes passed. Stopping.")
            break

        pnl_start = exchange.get_pnl()
        pnl_prev = pnl_start

        print("\n" + "-" * 65)
        print(f"TRADE LOOP @ {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print("-" * 65)

        start_time_1_loop = time.time()
        while True:
            if time.time() - start_time_1_loop >= 60:
                print("30 minutes passed. Stopping.")
                break
            print_positions_and_pnl(always_display=[p[0] for p in FUTURES] + [p[1] for p in FUTURES])

            for stock_id, future_id in FUTURES:

                discount = get_future_book_discount(future_id) # exp(r tau)

                side, vol = trade_pair_future(stock_id, future_id, discount)

                if side != "none":
                    
                    vol_hedge = hedge_pair_future(stock_id, future_id, discount, side)
                    traded_volume += vol + vol_hedge
                    trade_count += 2
                
                time.sleep(0.2)

            pnl_now = exchange.get_pnl()
            delta = pnl_now - pnl_prev
            pnl_prev = pnl_now
            print(f"[PnL] Total: {pnl_now:.2f} | Δ: {delta:.2f} | Volume: {traded_volume}")

            pnl_totals.append(delta)

       

    # Final stats
    mean_pnl = statistics.mean(pnl_totals)
    stdev_pnl = statistics.stdev(pnl_totals)

    print("\n" + "=" * 60)
    print("Trading session completed.")
    print("PnL Gained :", sum(pnl_totals))
    print(f"Mean PnL min: {mean_pnl:.5f}")
    print(f"Std Dev min:  {stdev_pnl:.5f}")
    print(f"Sharpe rate min: {mean_pnl / stdev_pnl:.5f}")
    print(f"Total volume traded min: {traded_volume/30}")
    print(f"Number of trades min: {trade_count/30}")
    print("=" * 60)
# %%