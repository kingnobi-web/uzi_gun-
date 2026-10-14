import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
import bot


class TradingTests(unittest.TestCase):
    def setUp(self):
        self.mt = Mock()
        for key, value in dict(ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
                              ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1,
                              ORDER_FILLING_RETURN=2, SYMBOL_TRADE_EXECUTION_MARKET=2,
                              TRADE_ACTION_DEAL=1, ORDER_TIME_GTC=0,
                              TRADE_RETCODE_DONE=10009).items():
            setattr(self.mt, key, value)
        self.mt.account_info.return_value = NS(login=123, server='Exness', trade_allowed=True, trade_expert=True)
        self.mt.terminal_info.return_value = NS(trade_allowed=True)
        self.mt.symbol_info.return_value = NS(volume_min=.01, volume_max=100,
                                             volume_step=.01, filling_mode=1,
                                             trade_contract_size=100)
        self.mt.symbol_info_tick.return_value = NS(ask=3001, bid=3000)
        self.mt.orders_get.return_value = ()
        self.mt.order_send.return_value = NS(retcode=10009, deal=99)
        self.position = NS(ticket=42, magic=bot.MAGIC, type=0, volume=.1)
        self.args = NS(account=123, symbol='XAUUSDm', cycles=1, deviation=20)

    @patch('bot.time.sleep')
    def test_buy_wait_close_exact_position(self, sleep):
        self.mt.positions_get.side_effect = [(), (self.position,), (self.position,), ()]
        bot.run(self.mt, self.args)
        buy, close = [call.args[0] for call in self.mt.order_send.call_args_list]
        self.assertEqual((buy['volume'], buy['type']), (.1, 0))
        self.assertNotIn('position', buy)
        self.assertEqual((close['position'], close['volume'], close['type']), (42, .1, 1))
        self.assertAlmostEqual(sleep.call_args.args[0], 5, delta=.1)

    def test_wrong_account_never_trades(self):
        self.args.account = 999
        with self.assertRaisesRegex(RuntimeError, 'account does not match'):
            bot.run(self.mt, self.args)
        self.mt.order_send.assert_not_called()

    def test_existing_position_never_trades(self):
        self.mt.positions_get.return_value = (self.position,)
        with self.assertRaisesRegex(RuntimeError, 'existing positions'):
            bot.run(self.mt, self.args)
        self.mt.order_send.assert_not_called()

    @patch('bot.time.sleep')
    def test_failed_close_stops_without_another_buy(self, sleep):
        self.mt.positions_get.side_effect = [(), (self.position,), (self.position,)]
        self.mt.order_send.side_effect = [NS(retcode=10009, deal=99), NS(retcode=10030, comment='Rejected')]
        with self.assertRaisesRegex(RuntimeError, 'Order incomplete'):
            bot.run(self.mt, self.args)
        self.assertEqual(self.mt.order_send.call_count, 2)

    @patch('bot.time.sleep', side_effect=KeyboardInterrupt)
    def test_interrupt_during_hold_attempts_close(self, sleep):
        self.mt.positions_get.side_effect = [(), (self.position,), (self.position,), ()]
        with self.assertRaises(KeyboardInterrupt):
            bot.run(self.mt, self.args)
        self.assertEqual(self.mt.order_send.call_args.args[0]['position'], 42)
