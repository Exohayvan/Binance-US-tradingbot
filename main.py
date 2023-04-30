import ccxt
import time
import pandas as pd
import numpy as np
from datetime import datetime
import json, requests
import talib
import os

if not os.path.isfile('bought_coins.json'):
    with open('bought_coins.json', 'w') as f:
        json.dump({}, f)

attempted_sells = 0
attempted_buys = 0
completed_sells = 0
completed_buys = 0
cost_of_buys = 0
cost_of_sales = 0
total_pairs = 0
owned_pairs = 0
api_key = 'YOUR_API_KEY'
api_secret = 'YOUR_API_SECRET'

exchange = ccxt.binanceus({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'urls': {
        'api': {
            'public': 'https://api.binance.us/api/v3',
            'private': 'https://api.binance.us/api/v3',
        },
    },
})

exchange.options['recvWindow'] = 15000

def get_account_balances():
    balance = exchange.fetch_balance()
    return {currency: balance['total'][currency] for currency in balance['total'] if balance['total'][currency] > 0}

def get_binance_chain_pairs():
    markets = exchange.load_markets()
    return [markets[market]['base'] for market in markets if markets[market]['quote'] == 'USDT' and f"{markets[market]['base']}/USDT" in markets and markets[market]['base'] not in ('XRP', 'BTC')]

def get_historical_data(symbol, timeframe):
    ohlcv = exchange.fetch_ohlcv(f"{symbol}/USDT", timeframe)
    return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

def calculate_technical_indicators(historical_data):
    close = np.array(historical_data['close'], dtype=float)
    high = np.array(historical_data['high'], dtype=float)
    low = np.array(historical_data['low'], dtype=float)

    sma20 = talib.SMA(close, timeperiod=20)
    sma50 = talib.SMA(close, timeperiod=50)
    rsi = talib.RSI(close, timeperiod=14)
    macd, macd_signal, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    upper, middle, lower = talib.BBANDS(close, timeperiod=20)

    return {
        'sma20': sma20,
        'sma50': sma50,
        'rsi': rsi,
        'macd': macd,
        'macd_signal': macd_signal,
        'bb_upper': upper,
        'bb_middle': middle,
        'bb_lower': lower,
    }

def trade(pair, action, amount, base_currency='USDT'):
    global attempted_sells, attempted_buys, completed_sells, completed_buys, cost_of_buys, cost_of_sales
    
    symbol = f"{pair}/{base_currency}"
    side = 'buy' if action == 'enter' else 'sell'

    if side == 'sell':
        balances = get_account_balances()
        if pair not in balances or balances[pair] < amount:
            print(f"Skipping {pair} sell order due to insufficient balance.")
            attempted_sells += 1
            return None
    else:
        attempted_buys += 1
        
        # Check the minimum notional value for the trading pair
        markets = exchange.load_markets()
        min_cost = markets[pair]['limits']['cost']['min']
        if amount < min_cost:
            print(f"Skipping {pair} buy order due to insufficient amount.")
            return None
        
        # Check account balance for the trading pair
        balances = get_account_balances()
        if base_currency not in balances:
            print(f"Skipping {pair} buy order due to insufficient {base_currency} balance.")
            return None
        elif balances[base_currency] < amount:
            print(f"Skipping {pair} buy order due to insufficient {base_currency} balance.")
            return None

    order = exchange.create_market_order(symbol, side, amount)
    print(f"Order: {order}")

    if side == 'sell':
        completed_sells += 1
        cost_of_sales += order['cost']
        
        # Remove the sold coin from the JSON file
        with open('bought_coins.json', 'r+') as f:
            bought_coins = json.load(f)
            if pair in bought_coins:
                del bought_coins[pair]
                f.seek(0)
                json.dump(bought_coins, f)
                f.truncate()
    else:
        completed_buys += 1
        cost_of_buys += order['cost']
        
        # Add the bought coin to the JSON file
        with open('bought_coins.json', 'r+') as f:
            bought_coins = json.load(f)
            bought_coins[pair] = {'amount': amount, 'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            f.seek(0)
            json.dump(bought_coins, f)
            f.truncate()

    return order

def trading_strategy(indicators):
    sma20 = indicators['sma20']
    sma50 = indicators['sma50']
    rsi = indicators['rsi']
    macd = indicators['macd']
    macd_signal = indicators['macd_signal']
    bb_upper = indicators['bb_upper']
    bb_middle = indicators['bb_middle']
    bb_lower = indicators['bb_lower']

    if sma20[-1] > sma50[-1] and sma20[-2] <= sma50[-2] and rsi[-1] < 70 and macd[-1] > macd_signal[-1]:
        return 'entry'
    elif sma20[-1] < sma50[-1] and sma20[-2] >= sma50[-2] or rsi[-1] > 70 or macd[-1] < macd_signal[-1]:
        return 'exit'

    return None

def diversify_portfolio(trading_pairs, base_amount):
    markets = exchange.load_markets()
    balances = get_account_balances()
    global total_pairs, owned_pairs, attempted_sells, attempted_buys, completed_sells, completed_buys, cost_of_buys, cost_of_sales  # Add global keyword to access global variables
    
    # Load the bought coins from the JSON file
    with open('bought_coins.json', 'r') as f:
        bought_coins = json.load(f)
    
    for pair in trading_pairs:
        if pair in bought_coins:
            owned_pairs += 1  # Increment owned_pairs
            print(f"Skipping {pair} due to already bought.")
            continue  # Skip the coin if it is already bought
        
        if pair not in balances:
            min_amount = markets[f'{pair}/USDT']['limits']['amount']['min']
            if base_amount >= min_amount:
                print(f"Trading {base_amount} USDT for {pair}...")
                trade(pair, 'enter', base_amount, base_currency='USDT')
            else:
                attempted_buys += 1  # Increment attempted_buys
                print(f"Skipping {pair} due to insufficient base amount.")
        else:
            print(f"Skipping {pair} due to already owned.")

def calculate_total_usdt_balance(balances):
    total_usdt_balance = sum([balances[pair] for pair in balances if pair != 'BUSD'])
    return total_usdt_balance

def sell_profit(pair, amount):
    # Get the current balance of the trading pair
    previous_balance = balances.get(pair, 0)

    # Sell the 10% profit for BTC
    new_balance = get_account_balances().get(pair, 0)
    profit = new_balance - previous_balance
    amount_to_trade_to_btc = profit * 0.10

    if amount_to_trade_to_btc > 0:
        print("Trading 10% profit to BTC...")
        trade(pair, 'sell', amount_to_trade_to_btc, base_currency='BTC')
    else:
        print(f"Skipping {pair} due to insufficient profit to sell.")

while True:
    try:
        print("Fetching trading pairs...")
        trading_pairs = get_binance_chain_pairs()
        total_pairs = len(trading_pairs)
        print(total_pairs)
        print(f"Trading pairs: {', '.join(trading_pairs)}")

        print("Updating account balances...")
        balances = get_account_balances()
        print(f"Account balances: {balances}")

        print("Calculating total USDT balance...")
        total_usdt_balance = calculate_total_usdt_balance(balances)
        print(f"USDT balance: {balances.get('USDT', 0)}")

        if total_usdt_balance > 0 and len(trading_pairs) > 0:
            base_amount = total_usdt_balance / len(trading_pairs)
            print("Diversifying portfolio...")
            diversify_portfolio(trading_pairs, base_amount)
        elif len(trading_pairs) == 0:
            print("No trading pairs found.")
        else:
            print("Insufficient USDT balance.")

        for pair in trading_pairs:
            if pair == "BTC":
                continue  # Skip trading for BTC pair

            print(f"Processing trading pair {pair}...")
            print("Fetching historical data...")
            historical_data = get_historical_data(pair, '15m')
            print("Calculating technical indicators...")
            technical_indicators = calculate_technical_indicators(historical_data)
            print("Applying trading strategy...")
            action = trading_strategy(technical_indicators)

            if action:
                print(f"Taking action: {action}")
                previous_balance = balances.get(pair, 0)
                order = trade(pair, action, base_amount)
                new_balance = get_account_balances().get(pair, 0)

                if action == 'exit' and new_balance > previous_balance:
                    sell_profit(pair, order['cost'])
            else:
                print("No action taken.")
    except Exception as e:
        print(f"Error: {e}")
        print("Retrying in 15 seconds...")
        time.sleep(15)
        continue
    print("Sleeping for 15 minutes before next iteration...")
    print(f"Summary of actions:")
    print(f"Attempted sells: {attempted_sells}")
    print(f"Attempted buys: {attempted_buys}")
    print(f"Completed sells: {completed_sells}")
    print(f"Completed buys: {completed_buys}")
    print(f"Cost of buys: {cost_of_buys}")
    print(f"Cost of sales: {cost_of_sales}")
    print(f"Total pairs: {total_pairs}")
    print(f"Owned pairs: {owned_pairs}")
    time.sleep(900)
