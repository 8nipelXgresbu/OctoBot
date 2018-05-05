import asyncio
import logging

import pandas
from ccxt import OrderNotFound, BaseError

from config.cst import PriceStrings, MARKET_SEPARATOR, TraderOrderType, CONFIG_EXCHANGES, PriceIndexes, \
    CONFIG_TIME_FRAME, TimeFrames


# https://github.com/ccxt/ccxt/wiki/Manual#api-methods--endpoints
class Exchange:
    def __init__(self, config, exchange_type, connect_to_online_exchange=True):
        self.exchange_type = exchange_type
        self.connect_to_online_exchange = connect_to_online_exchange
        self.client = None
        self.config = config
        self.name = self.exchange_type.__name__

        if self.connect_to_online_exchange:
            self.create_client()

            self.client.load_markets()

        self.all_currencies_price_ticker = None

        self.logger = logging.getLogger(self.name)

    def enabled(self):
        # if we can get candlestick data
        if not self.connect_to_online_exchange \
                or (self.name in self.config[CONFIG_EXCHANGES] and self.client.has['fetchOHLCV']):
            return True
        else:
            self.logger.warning("Exchange {0} is currently disabled".format(self.name))
            return False

    def create_client(self):
        if self.check_config():
            if self.connect_to_online_exchange:
                self.client = self.exchange_type({
                    'apiKey': self.config["exchanges"][self.name]["api-key"],
                    'secret': self.config["exchanges"][self.name]["api-secret"],
                    'verbose': False,
                    'enableRateLimit': True
                })
            else:
                self.client = self.exchange_type({'verbose': False})
        else:
            self.client = self.exchange_type({'verbose': False})
        self.client.logger.setLevel(logging.INFO)

    def check_config(self):
        if not self.config["exchanges"][self.name]["api-key"] \
                and not self.config["exchanges"][self.name]["api-secret"]:
            return False
        else:
            return True

    def get_name(self):
        return self.name

    # 'free':  {           // money, available for trading, by currency
    #         'BTC': 321.00,   // floats...
    #         'USD': 123.00,
    #         ...
    #     },
    #
    #     'used':  { ... },    // money on hold, locked, frozen, or pending, by currency
    #
    #     'total': { ... },    // total (free + used), by currency
    def get_balance(self):
        return self.client.fetchBalance()

    def get_symbol_prices(self, symbol, time_frame, limit=None, data_frame=True):
        if limit:
            candles = self.client.fetch_ohlcv(symbol, time_frame.value, limit=limit)
        else:
            candles = self.client.fetch_ohlcv(symbol, time_frame.value)

        if data_frame:
            return self.candles_array_to_data_frame(candles)
        else:
            return candles

    @staticmethod
    def candles_array_to_data_frame(candles_array):
        prices = {PriceStrings.STR_PRICE_HIGH.value: [],
                  PriceStrings.STR_PRICE_LOW.value: [],
                  PriceStrings.STR_PRICE_OPEN.value: [],
                  PriceStrings.STR_PRICE_CLOSE.value: [],
                  PriceStrings.STR_PRICE_VOL.value: [],
                  PriceStrings.STR_PRICE_TIME.value: []}

        for c in candles_array:
            prices[PriceStrings.STR_PRICE_TIME.value].append(float(c[PriceIndexes.IND_PRICE_TIME.value]))
            prices[PriceStrings.STR_PRICE_OPEN.value].append(float(c[PriceIndexes.IND_PRICE_OPEN.value]))
            prices[PriceStrings.STR_PRICE_HIGH.value].append(float(c[PriceIndexes.IND_PRICE_HIGH.value]))
            prices[PriceStrings.STR_PRICE_LOW.value].append(float(c[PriceIndexes.IND_PRICE_LOW.value]))
            prices[PriceStrings.STR_PRICE_CLOSE.value].append(float(c[PriceIndexes.IND_PRICE_CLOSE.value]))
            prices[PriceStrings.STR_PRICE_VOL.value].append(float(c[PriceIndexes.IND_PRICE_VOL.value]))

        return pandas.DataFrame(data=prices)

    # return up to ten bidasks on each side of the order book stack
    def get_order_book(self, symbol, limit=30):
        return self.client.fetchOrderBook(symbol, limit)

    def get_recent_trades(self, symbol):
        try:
            return self.client.fetch_trades(symbol)
        except BaseError as e:
            self.logger.error("Failed to get recent trade {0}".format(e))
            return None

    def get_market_price(self, symbol):
        order_book = self.get_order_book(symbol)
        bid = order_book['bids'][0][0] if len(order_book['bids']) > 0 else None
        ask = order_book['asks'][0][0] if len(order_book['asks']) > 0 else None
        spread = (ask - bid) if (bid and ask) else None
        return {'bid': bid, 'ask': ask, 'spread': spread}

    # A price ticker contains statistics for a particular market/symbol for some period of time in recent past (24h)
    def get_price_ticker(self, symbol):
        try:
            return self.client.fetch_ticker(symbol)
        except BaseError as e:
            self.logger.error("Failed to get_price_ticker {0}".format(e))
            return None

    def get_all_currencies_price_ticker(self):
        try:
            self.all_currencies_price_ticker = self.client.fetch_tickers()
            return self.all_currencies_price_ticker
        except BaseError as e:
            self.logger.error("Failed to get_all_currencies_price_ticker {0}".format(e))
            return None

    # ORDERS
    # {
    #     'id':        '12345-67890:09876/54321', // string
    #     'datetime':  '2017-08-17 12:42:48.000', // ISO8601 datetime with milliseconds
    #     'timestamp':  1502962946216, // order placing/opening Unix timestamp in milliseconds
    #     'status':    'open',         // 'open', 'closed', 'canceled'
    #     'symbol':    'ETH/BTC',      // symbol
    #     'type':      'limit',        // 'market', 'limit'
    #     'side':      'buy',          // 'buy', 'sell'
    #     'price':      0.06917684,    // float price in quote currency
    #     'amount':     1.5,           // ordered amount of base currency
    #     'filled':     1.1,           // filled amount of base currency
    #     'remaining':  0.4,           // remaining amount to fill
    #     'cost':       0.076094524,   // 'filled' * 'price'
    #     'trades':   [ ... ],         // a list of order trades/executions
    #     'fee':      {                // fee info, if available
    #         'currency': 'BTC',       // which currency the fee is (usually quote)
    #         'cost': 0.0009,          // the fee amount in that currency
    #         'rate': 0.002,           // the fee rate (if available)
    #     },
    #     'info':     { ... },         // the original unparsed order structure as is
    # }
    def get_order(self, order_id):
        if self.client.has['fetchOrder']:
            return asyncio.get_event_loop().run_until_complete(self.client.fetch_order(order_id))
        else:
            return None

    def get_all_orders(self, symbol=None, since=None, limit=None):
        if self.client.has['fetchOrders']:
            return self.client.fetchOrders(symbol=symbol, since=since, limit=limit, params={})
        else:
            return None

    def get_open_orders(self, symbol=None, since=None, limit=None):
        if self.client.has['fetchClosedOrders']:
            return self.client.fetchClosedOrders(symbol=symbol, since=since, limit=limit, params={})
        else:
            return None

    def get_my_recent_trades(self, symbol=None, since=None, limit=None):
        return self.client.fetchMyTrades(symbol=symbol, since=since, limit=limit, params={})

    def cancel_order(self, order_id):
        try:
            self.client.cancel_order(order_id)
            return True
        except OrderNotFound:
            return False

    def create_order(self, order_type, symbol, quantity, price=None, stop_price=None):
        if order_type == TraderOrderType.BUY_MARKET:
            self.client.create_market_buy_order(symbol, quantity)
        elif order_type == TraderOrderType.BUY_LIMIT:
            self.client.create_limit_buy_order(symbol, quantity, price)
        elif order_type == TraderOrderType.SELL_MARKET:
            self.client.create_market_sell_order(symbol, quantity)
        elif order_type == TraderOrderType.SELL_LIMIT:
            self.client.create_limit_sell_order(symbol, quantity, price)
        elif order_type == TraderOrderType.STOP_LOSS:
            pass
        elif order_type == TraderOrderType.STOP_LOSS_LIMIT:
            pass
        elif order_type == TraderOrderType.TAKE_PROFIT:
            pass
        elif order_type == TraderOrderType.TAKE_PROFIT_LIMIT:
            pass

    def symbol_exists(self, symbol):
        if symbol in self.client.symbols:
            return True
        else:
            return False

    def time_frame_exists(self, time_frame):
        if time_frame in self.client.timeframes:
            return True
        else:
            return False

    # Return currency, market
    @staticmethod
    def split_symbol(symbol):
        splitted = symbol.split(MARKET_SEPARATOR)
        return splitted[0], splitted[1]

    # Merge currency and market
    @staticmethod
    def merge_currencies(currency, market):
        return "{0}/{1}".format(currency, market)

    @staticmethod
    def get_config_time_frame(config):
        if CONFIG_TIME_FRAME in config:
            result = []
            for time_frame in config[CONFIG_TIME_FRAME]:
                try:
                    result.append(TimeFrames(time_frame))
                except ValueError:
                    logging.warning("Time frame not found : {0}".format(time_frame))
            return result
        else:
            return TimeFrames

    def get_rate_limit(self):
        return self.exchange_type.rateLimit / 1000

    def get_name(self):
        return self.name