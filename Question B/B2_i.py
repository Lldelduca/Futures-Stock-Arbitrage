# %%
import datetime as dt
import time
import statistics 
import logging
import numpy as np
from optibook.synchronous_client import Exchange

exchange = Exchange()
exchange.connect()

logging.getLogger("client").setLevel("ERROR")


# ========== Helper Functions ==========

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
    book = exchange.get_last_price_book(future_id)
    future = exchange.get_instruments()[future_id]
    interest_rate = future.interest_rate
    maturity = future.expiry
    current_date = dt.datetime.now()
    tau = year_fraction(maturity) - year_fraction(current_date)
    discount_factor = np.exp(interest_rate * tau)
    return discount_factor

def trade_would_breach_position_limit(instrument_id, volume, side, position_limit=100):
    positions = exchange.get_positions()
    position_instrument = positions[instrument_id]
    if side == "bid":
        return position_instrument + volume > position_limit
    elif side == "ask":
        return position_instrument - volume < -position_limit
    else:
        raise Exception(f"Invalid side: {side}")

def trade_would_breach_position_limit_future(instrument_id, volume, side, discount_factor, position_limit=100):
    positions = exchange.get_positions()
    position_instrument = positions[instrument_id] * discount_factor
    if side == "bid":
        return position_instrument + volume > position_limit
    elif side == "ask":
        return position_instrument - volume < -position_limit
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

        time.sleep(0.20)

    time.sleep(1.0)

    positions = exchange.get_positions()
    pnl = exchange.get_pnl()
    print(f"\nPositions after: {positions}")
    print(f"\nPnL after: {pnl:.2f}")


def trade_pair_future(stock_id, stock_id_future, discount_factor):
    stock_order_book = exchange.get_last_price_book(stock_id)
    stock_order_book_future = exchange.get_last_price_book(stock_id_future)
    side = "none"

    if not (stock_order_book and stock_order_book.bids and stock_order_book.asks):
        print(f"Order book for {stock_id} missing bids/asks. Skipping.")
        time.sleep(0.2)
        return "none"
    
    best_bid_price = stock_order_book.bids[0].price
    best_ask_price = stock_order_book.asks[0].price

    if stock_order_book_future.asks:
        best_ask_price_future = stock_order_book_future.asks[0].price
        if best_ask_price_future < best_bid_price * discount_factor + 0.05:
            side = "bid"
            price = best_ask_price_future

    if stock_order_book_future.bids:
        best_bid_price_future = stock_order_book_future.bids[0].price
        if best_bid_price_future > best_ask_price * discount_factor + 0.05:
            side = "ask"
            price = best_bid_price_future

    if side != "none":
        volume = 1
        stock_hedge_side = "ask" if side == "bid" else "bid"
        if (not trade_would_breach_position_limit_future(stock_id_future, volume, side, discount_factor)
            and not trade_would_breach_position_limit(stock_id, volume, stock_hedge_side)):
            print(f"Inserting {side} for {stock_id_future}: {volume:.0f} lot(s) at {price:.2f}")
            exchange.insert_order(
                instrument_id=stock_id_future,
                price=price,
                volume=volume,
                side=side,
                order_type="ioc",
            )
            return side
        else:
            print(f"Skipping {side} for {stock_id_future} to avoid position-limit breach.")
    
    return "none"

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
        stock_order_book = exchange.get_last_price_book(stock_id)
        if not (stock_order_book and stock_order_book.bids):
            print(f"{stock_id} has no bids. Skipping hedge.")
            time.sleep(0.2)
            return
        price_hedge = stock_order_book.bids[0].price
        side_hedge = "ask"
    elif outstanding_position < 0:
        stock_order_book = exchange.get_last_price_book(stock_id)
        if not (stock_order_book and stock_order_book.asks):
            print(f"{stock_id} has no asks. Skipping hedge.")
            time.sleep(0.2)
            return
        price_hedge = stock_order_book.asks[0].price
        side_hedge = "bid"
    else:
        return  

    volume_hedge = 1
    if not trade_would_breach_position_limit(stock_id, volume_hedge, side_hedge):
        print(f"Inserting {side_hedge} for {stock_id}: {volume_hedge} lot(s) at {price_hedge:.2f}")
        exchange.insert_order(
            instrument_id=stock_id,
            price=price_hedge,
            volume=volume_hedge,
            side=side_hedge,
            order_type="ioc",
        )

def get_stocks():
    instruments = list(exchange.get_instruments().keys())
    stock = []
    for instrument_name in instruments:
        parts = instrument_name.split("_")
        if len(parts) == 1:
            stock.append(instrument_name)
    return stock

# ========== Main Script ==========

if __name__ == "__main__":
    pnl_totals = []
    traded_volum = 0 # here is also the number of trades 

    STOCK = get_stocks()
    FUTURES = [(stock, list(get_futures_of_stock(stock).keys())[0])
               for stock in STOCK if len(get_futures_of_stock(stock)) != 0]

    start_time = time.time()
    max_duration = 30 * 60  # 30 minutes

    while True:
        current_time = time.time()
        elapsed = current_time - start_time
        
        if elapsed >= max_duration:
            print("30 minutes passed. Stopping loop.")
            break

        pnl_start = exchange.get_pnl()
        pnl_prev = pnl_start        

        start_1_loop = time.time()
        while True:
            print_positions_and_pnl(always_display=[p[0] for p in FUTURES] + [p[1] for p in FUTURES])

            if time.time() - start_1_loop >= 60:
                # 1 min has passed
                break
            for stock_id, stock_id_future in FUTURES:
                discount_rate = get_future_book_discount(stock_id_future)

                trade_side = trade_pair_future(stock_id, stock_id_future, discount_rate)

                if trade_side != "none":
                    traded_volum += 1
                    hedge_pair_future(stock_id, stock_id_future, discount_rate, trade_side)
            
            time.sleep(0.2)

        pnl_now = exchange.get_pnl()
        delta = pnl_now - pnl_prev
        pnl_prev = pnl_now

        print(f"[PnL update] Total: {pnl_now:.2f} | Change: {delta:.2f}")
        print(f"Current volume traded: {traded_volum}")
        print("Sleeping for 0.2 seconds.")

        
        pnl_totals.append(delta)

    mean_pnl = statistics.mean(pnl_totals)
    stdev_pnl = statistics.stdev(pnl_totals)

    print("\n===============================================================")
    print("All runs finished.")
    print("PnL changes across runs:")
    print(f"Mean PnL per min: {mean_pnl:.5f}")
    print(f"Standard deviation per min: {stdev_pnl:.5f}")
    print(f"Total PnL 30 min: {sum(pnl_totals)}")
    print(f"Sharpe Ratio min: {mean_pnl / stdev_pnl :.5f}")
    print(f"Total volume traded min: {traded_volum/30}")
    print(f"Number of Trades min: {traded_volum/30}")

    print("===============================================================")
    restart_position()
# %%
