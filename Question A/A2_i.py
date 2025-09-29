import datetime as dt
import time
import statistics 
import logging

from optibook.synchronous_client import Exchange

exchange = Exchange()
exchange.connect()

logging.getLogger("client").setLevel("ERROR")


def trade_would_breach_position_limit(instrument_id, volume, side, position_limit=100):
    positions = exchange.get_positions()
    position_instrument = positions[instrument_id]

    if side == "bid":
        return position_instrument + volume > position_limit
    elif side == "ask":
        return position_instrument - volume < -position_limit
    else:
        raise Exception(f"Invalid side provided: {side}, expecting 'bid' or 'ask'.")


def print_positions_and_pnl(always_display=None):
    positions = exchange.get_positions()
    print("Positions:")
    for instrument_id in positions:
        if (
            not always_display
            or instrument_id in always_display
            or positions[instrument_id] != 0
        ):
            print(f"  {instrument_id:20s}: {positions[instrument_id]:4.0f}")

    pnl = exchange.get_pnl()
    if pnl:
        print(f"\nPnL: {pnl:.2f}")


def trade_pair(stock_id, stock_id_dual, position_dual):
    stock_order_book = exchange.get_last_price_book(stock_id)
    stock_order_book_dual = exchange.get_last_price_book(stock_id_dual)

    side = "none"

    if not (stock_order_book and stock_order_book.bids and stock_order_book.asks):
        print(
            f"Order book for {stock_id} does not have bids or offers. Skipping iteration."
        )
        time.sleep(0.2)
        return
    else:
        best_bid_price = stock_order_book.bids[0].price
        best_ask_price = stock_order_book.asks[0].price

    if stock_order_book_dual.asks:
        best_ask_price_dual = stock_order_book_dual.asks[0].price

        if best_bid_price > best_ask_price_dual:  # dual undervalued → buy dual
            side = "bid"
            price = best_ask_price_dual

        if best_ask_price >= best_ask_price_dual and position_dual < 0:
            side = "bid"
            price = best_ask_price_dual

    if stock_order_book_dual.bids:
        best_bid_price_dual = stock_order_book_dual.bids[0].price

        if best_ask_price < best_bid_price_dual:  # dual overvalued → sell dual
            side = "ask"
            price = best_bid_price_dual

        if best_bid_price <= best_bid_price_dual and position_dual > 0:
            side = "ask"
            price = best_bid_price_dual

    if side != "none":
        volume = 1
        if not trade_would_breach_position_limit(stock_id_dual, volume, side):
            print(
                f"Inserting {side} for {stock_id_dual}: {volume:.0f} lot(s) at price {price:.2f}."
            )
            exchange.insert_order(
                instrument_id=stock_id_dual,
                price=price,
                volume=volume,
                side=side,
                order_type="ioc",
            )
        else:
            print(
                f"Not inserting {volume:.0f} lot {side} for {stock_id_dual} "
                f"to avoid position-limit breach."
            )


# Instruments
PAIRS = [
    ("ASML", "ASML_DUAL"),
    ("SAP", "SAP_DUAL"),
]


if __name__ == "__main__":
    pnl_totals = []
    traded_volume = 0
    trade_count = 0

    start_time = time.time()
    max_duration = 30 * 60  # 30 mins

    pnl_start = exchange.get_pnl()
    pnl_prev = pnl_start

    while True:
        if time.time() - start_time >= max_duration:
            print("30 minutes passed. Stopping.")
            break

        print("\n-----------------------------------------------------------------")
        print(f"TRADE LOOP ENTERED AT {str(dt.datetime.now()):18s} UTC.")
        print("-----------------------------------------------------------------")

        print_positions_and_pnl(always_display=[p[0] for p in PAIRS] + [p[1] for p in PAIRS])
        print("")

        # Inner loop: run for 60 seconds, repeatedly trading all pairs
        start_1_loop = time.time()
        while True:
            if time.time() - start_1_loop >= 60:
                # 1 minute has passed
                break

            positions = exchange.get_positions()
            for stock_id, stock_id_dual in PAIRS:
                position_dual = positions[stock_id_dual]
                trade_pair(stock_id, stock_id_dual, position_dual)
                trade_count += 1
                traded_volume += 1

            time.sleep(0.2)  # small pause between trades

        # PnL tracking after inner loop
        pnl_now = exchange.get_pnl()
        delta = pnl_now - pnl_prev
        pnl_prev = pnl_now
        pnl_totals.append(delta)

        print(f"[PnL update] Total: {pnl_now:.2f} | Last change: {delta:.2f}")

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

