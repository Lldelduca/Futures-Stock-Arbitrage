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


def restart_position():
    MIN_SELLING_PRICE = 0.10
    MAX_BUYING_PRICE = 100000.00

    positions = exchange.get_positions()
    pnl = exchange.get_pnl()

    print(f"Positions before: {positions}")
    print(f"\nPnL before: {pnl:.2f}")

    print(f"\nTrading out of positions")
    for iid, pos in positions.items():
        if pos > 0:
            print(
                f"-- Inserting sell order for {pos} lots of {iid}, with limit price {MIN_SELLING_PRICE:.2f}"
            )
            exchange.insert_order(
                iid, price=MIN_SELLING_PRICE, volume=pos, side="ask", order_type="ioc"
            )
        elif pos < 0:
            print(
                f"-- Inserting buy order for {abs(pos)} lots of {iid}, with limit price {MAX_BUYING_PRICE:.2f}"
            )
            exchange.insert_order(
                iid, price=MAX_BUYING_PRICE, volume=-pos, side="bid", order_type="ioc"
            )
        else:
            print(f"-- No initial position in {iid}, skipping..")

        time.sleep(0.10)

    time.sleep(1.0)

    positions = exchange.get_positions()
    pnl = exchange.get_pnl()
    print(f"\nPositions after: {positions}")
    print(f"\nPnL after: {pnl:.2f}")

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



def max_volume_cover(stock_id_future, stock_id_future_2, operation_future, volume_future, volume_future_2, conversion_factor, future_limit=100, future_limit_2=100):
    positions = exchange.get_positions()
    pos_future = positions[stock_id_future]
    pos_future_2 = positions[stock_id_future_2]

    if operation_future == "bid":  
        max_future_buy = future_limit - pos_future
        
        max_future_2_sell = future_limit_2 + pos_future_2  
        
        max_future_2_sell_in_future_units = max_future_2_sell * conversion_factor
        
        volume_future_cover = min(
            max_future_buy,
            max_future_2_sell_in_future_units,
            volume_future,
            volume_future_2 * conversion_factor
        )
        
        volume_future_cover_2 = volume_future_cover / conversion_factor

    elif operation_future == "ask":  
        max_future_sell = future_limit + pos_future  
        
        max_future_2_buy = future_limit_2 - pos_future_2
        
        max_future_2_buy_in_future_units = max_future_2_buy * conversion_factor
        
        volume_future_cover = min(
            max_future_sell,
            max_future_2_buy_in_future_units, 
            volume_future,
            volume_future_2 * conversion_factor
        )
        
        volume_future_cover_2 = volume_future_cover / conversion_factor
        
    else:
        return 0, 0

    volume_future_cover_2 = math.floor(volume_future_cover_2)
    volume_future_cover = math.floor(volume_future_cover_2 * conversion_factor)  
    
    return volume_future_cover_2, volume_future_cover

def trade_pair_future(stock_id_future, stock_id_future_2, discount_factor, discount_factor_2):
   
    future_book = exchange.get_last_price_book(stock_id_future)
    future_book_2 = exchange.get_last_price_book(stock_id_future_2)

    
    convert_factor = discount_factor_2 / discount_factor  # This is correct


    if not (future_book and future_book.bids and future_book.asks and
            future_book_2 and future_book_2.bids and future_book_2.asks):
        print(f"Order book incomplete. Skipping.")
        return "none", 0

    best_bid = future_book.bids[0].price
    best_ask = future_book.asks[0].price
    bid_future_2 = future_book_2.bids[0].price
    ask_future_2 = future_book_2.asks[0].price

    side = "none"
    price_future_2 = None
    volume_future = None
    volume_future_2 = None  


    spread_threshold = 0.05

    if ask_future_2 < best_bid * convert_factor - spread_threshold:
        side = "ask"  
        price_future_2 = ask_future_2
        volume_future = future_book.bids[0].volume  
        volume_future_2 = future_book_2.asks[0].volume  
        print(f"ARB FOUND: Buy {stock_id_future_2} @ {ask_future_2:.2f}, Sell {stock_id_future} @ ~{best_bid:.2f}")
        print(f"  Ratio: {ask_future_2/best_bid:.4f} vs Fair: {convert_factor:.4f}")


    elif bid_future_2 > best_ask * convert_factor + spread_threshold:
        side = "bid"   
        price_future_2 = bid_future_2
        volume_future = future_book.asks[0].volume  
        
        volume_future_2 = future_book_2.bids[0].volume  
        print(f"ARB FOUND: Sell {stock_id_future_2} @ {bid_future_2:.2f}, Buy {stock_id_future} @ ~{best_ask:.2f}")
        print(f"  Ratio: {bid_future_2/best_ask:.4f} vs Fair: {convert_factor:.4f}")

    if side != "none":

        future_vol_2, future_vol = max_volume_cover(
            stock_id_future, stock_id_future_2, side, volume_future, volume_future_2, convert_factor
        )

        if future_vol_2 > 0:

            if side == "bid":  
                
                exchange.insert_order(
                    instrument_id=stock_id_future_2,
                    price=price_future_2,
                    volume=future_vol_2,
                    side="ask",  
                    order_type="ioc",
                )
                print(f"  EXECUTED: Sold {future_vol_2} of {stock_id_future_2} @ {price_future_2:.2f}")
            else:  
                
                exchange.insert_order(
                    instrument_id=stock_id_future_2,
                    price=price_future_2,
                    volume=future_vol_2,
                    side="bid",  
                    order_type="ioc",
                )
                print(f"  EXECUTED: Bought {future_vol_2} of {stock_id_future_2} @ {price_future_2:.2f}")
                
            return side, future_vol_2

    return "none", 0

def cover_pair_future(stock_id_future, stock_id_future_2, convert_factor, trade_side):

    positions = exchange.get_positions()
    if trade_side == "bid":
        trade_adjustment = 1
    elif trade_side == "ask":
        trade_adjustment = -1
    else:
        trade_adjustment = 0

    outstanding_position = round(positions[stock_id_future] + positions[stock_id_future_2] * convert_factor + trade_adjustment)

    if outstanding_position > 0:
        future_book = exchange.get_last_price_book(stock_id_future)
        if not (future_book and future_book.bids):
            print(f"{stock_id_future} has no bids. Skipping cover.")
            return 0
        price = future_book.bids[0].price
        side = "ask"
        volume = outstanding_position
    elif outstanding_position < 0:
        future_book = exchange.get_last_price_book(stock_id_future)
        if not (future_book and future_book.asks):
            print(f"{stock_id_future} has no asks. Skipping cover.")
            return 0
        price = future_book.asks[0].price
        side = "bid"
        volume = -outstanding_position
    else:
        return 0

    if not trade_would_breach_position_limit(stock_id_future, volume, side):
        exchange.insert_order(
            instrument_id=stock_id_future,
            price=price,
            volume=volume,
            side=side,
            order_type="ioc",
        )
        return volume
    return False



def get_stocks():
    instruments = exchange.get_instruments()
    return [name for name in instruments if "_" not in name]




if __name__ == "__main__":
    pnl_totals = []
    traded_volume = 0
    trade_count = 0

    STOCKS = get_stocks()
    FUTURES_id = list(get_futures_of_stock(STOCKS[0]).keys())

    F_F = [(FUTURES_id[-1], FUTURES_id[-2])] # can be a list of tuples if more futures from other stocks

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

        print_positions_and_pnl(always_display=[p[0] for p in F_F] + [p[1] for p in F_F])
        
        start_1_loop = time.time()
        while True:

            if time.time() - start_1_loop >= 60:
                # 1 min has passed
                break

            for future_id, future_id_2 in F_F:
                discount = get_future_book_discount(future_id)
                discount_2 = get_future_book_discount(future_id_2)

                side, vol = trade_pair_future(future_id, future_id_2, discount, discount_2)

                if side != "none":
                    
                    vol_cover = cover_pair_future(future_id, future_id_2, discount_2 / discount , side)
                    traded_volume += vol + vol_cover
                    trade_count += 2
                    
                time.sleep(0.2)


        pnl_now = exchange.get_pnl()
        delta = pnl_now - pnl_prev
        pnl_prev = pnl_now
        pnl_totals.append(delta)

       


    # Final stats
    mean_pnl = statistics.mean(pnl_totals)
    stdev_pnl = statistics.stdev(pnl_totals)

    print("\n" + "=" * 60)
    print("Trading session completed.")
    print("PnL Gained :", sum(pnl_totals))
    print(f"Mean PnL min: {mean_pnl:.5f}")
    print(f"Std Dev min :  {stdev_pnl:.5f}")
    print(f"Sharpe rate min: {mean_pnl / stdev_pnl:.5f}")
    print(f"Total volume traded 30 min: {traded_volume/30}")
    print(f"Number of trades min: {trade_count/30}")
    print("=" * 60)
    restart_position()

    
# %%