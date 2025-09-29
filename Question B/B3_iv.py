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

    if operation_future == "bid":  # BUY future, SELL future_2

        max_future_buy = future_limit - pos_future
        
        max_future_2_sell = future_limit_2 + pos_future_2  
        
        max_future_2_sell_in_future_units = max_future_2_sell * conversion_factor
        
        available_future_volume = volume_future  
        available_future_2_volume_in_future_units = volume_future_2 * conversion_factor  
        
        
        volume_future_cover = min(
            max_future_buy,                    
            max_future_2_sell_in_future_units,
            available_future_volume,           
            available_future_2_volume_in_future_units 
        )
        
        volume_future_cover_2 = volume_future_cover / conversion_factor

    elif operation_future == "ask":  
        
        max_future_sell = future_limit + pos_future
        

        max_future_2_buy = future_limit_2 - pos_future_2
        

        max_future_2_buy_in_future_units = max_future_2_buy * conversion_factor
        

        available_future_volume = volume_future 
        available_future_2_volume_in_future_units = volume_future_2 * conversion_factor  
        
        
        volume_future_cover = min(
            max_future_sell,                   
            max_future_2_buy_in_future_units,  
            available_future_volume,           
            available_future_2_volume_in_future_units 
        )
        

        volume_future_cover_2 = volume_future_cover / conversion_factor
        
    else:
        return 0, 0


    volume_future_cover_2 = math.floor(volume_future_cover_2)
    volume_future_cover = math.floor(volume_future_cover)
    
    
    print(f"Volume calc: future_2={volume_future_cover_2}, future={volume_future_cover}, op={operation_future}")
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





def get_stocks():
    instruments = exchange.get_instruments()
    return [name for name in instruments if "_" not in name]


def pre_hedge_profit(stock_id, vol_f_1, vol_f_2, discount_1, discount_2, price_1, price_2):
    
    delta = round(vol_f_1 * discount_1 + vol_f_2 * discount_2)
    
    if delta == 0:
        return price_1 * vol_f_1 + price_2 * vol_f_2

    elif delta < 0:
        # should buy stock

        book = exchange.get_last_price_book(stock_id)
        if not (book and book.asks):
            # negatif profit, so operation will not be executed
            return -1

        price = book.asks[0].price

        return price_1 * vol_f_1 + price_2 * vol_f_2 - delta * price
    
    else:
        # should sell stock

        book = exchange.get_last_price_book(stock_id)
        if not (book and book.bids):
            # negatif profit, so operation will not be executed
            return -1

        price = book.bids[0].price

        return price_1 * vol_f_1 + price_2 * vol_f_2 - delta * price


def hedge_position(stock_id, future_1_id, future_2_id, discount_1, discount_2, max_pos=100, tolerance=1):

    total_volume = 0  

    while True:
        positions = exchange.get_positions()

        delta = round(positions[future_1_id] * discount_1 + positions[future_2_id] * discount_2 + positions[stock_id])

        if abs(delta) <= tolerance:
            break

        book_stock = exchange.get_last_price_book(stock_id)
        book_future_1 = exchange.get_last_price_book(future_1_id)
        book_future_2 = exchange.get_last_price_book(future_2_id)

        best_id, best_price, side, volume = None, None, None, 0

        if delta < 0:
            # negative delta → buy cheapest instrument
            candidates = []
            if book_stock and book_stock.asks:
                candidates.append((stock_id, book_stock.asks[0].price, "bid", 1.0))
            if book_future_1 and book_future_1.asks:
                candidates.append((future_1_id, book_future_1.asks[0].price * discount_1, "bid", discount_1))
            if book_future_2 and book_future_2.asks:
                candidates.append((future_2_id, book_future_2.asks[0].price * discount_2, "bid", discount_2))

            best_id, best_price, side, discount_factor = min(candidates, key=lambda x: x[1])

            volume = min(abs(delta) / discount_factor, abs(-max_pos - positions[best_id]))

        elif delta > 0:
            # positive delta → sell most expensive instrument
            candidates = []
            if book_stock and book_stock.bids:
                candidates.append((stock_id, book_stock.bids[0].price, "ask", 1.0))
            if book_future_1 and book_future_1.bids:
                candidates.append((future_1_id, book_future_1.bids[0].price * discount_1, "ask", discount_1))
            if book_future_2 and book_future_2.bids:
                candidates.append((future_2_id, book_future_2.bids[0].price * discount_2, "ask", discount_2))

            best_id, best_price, side, discount_factor = max(candidates, key=lambda x: x[1])

            volume = min(abs(delta) / discount_factor, abs(max_pos + positions[best_id]))


        if best_id is None or volume <= 0:
            break

        print(f"Hedging {side} {volume} {best_id} at {best_price:.2f}")
        exchange.insert_order(
            instrument_id=best_id,
            price=best_price,
            volume=volume,
            side=side,
            order_type="ioc",
        )

        total_volume += volume

    return total_volume



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
    print(f"Total volume traded 30 min: {traded_volume}")
    print(f"Number of trades min: {trade_count/30}")
    print("=" * 60)
    restart_position()

# %%