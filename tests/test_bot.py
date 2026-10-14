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
                              ACCOUNT_MARGIN_MODE_RETAIL_HEDGING=2, TIMEFRAME_M1=1, TRADE_RETCODE_DONE=10009).items():
            setattr(self.mt, key, value)
        self.mt.account_info.return_value = NS(login=123, server='Exness', margin_mode=2, trade_allowed=True, trade_expert=True)
        self.mt.terminal_info.return_value = NS(trade_allowed=True)
        self.mt.symbol_info.return_value = NS(volume_min=.01, volume_max=100,
                                             volume_step=.01, filling_mode=1,
                                             trade_contract_size=100)
        self.mt.symbol_info_tick.return_value = NS(ask=3001, bid=3000)
        self.mt.orders_get.return_value = ()
        self.mt.order_send.return_value = NS(retcode=10009, deal=99)
        self.position = NS(ticket=42, magic=bot.MAGIC, type=0, volume=.01)
        self.args = NS(account=123, symbol='XAUUSDm', cycles=1, deviation=20)

    def simulate(self, side=0, fail_open=None, fail_close=None):
        active = []
        entries = 0
        def execute(request):
            nonlocal entries
            if 'position' in request:
                if request['position'] == fail_close:
                    return NS(retcode=10030, comment='Rejected')
                active[:] = [p for p in active if p.ticket != request['position']]
            else:
                entries += 1
                if entries == fail_open:
                    return NS(retcode=10030, comment='Rejected')
                active.append(NS(ticket=entries, magic=bot.MAGIC, type=side, volume=.01))
            return NS(retcode=10009, deal=entries)
        self.mt.positions_get.side_effect = lambda **kwargs: tuple(active)
        self.mt.order_send.side_effect = execute
        return active

    def test_both_directions_open_ten_and_close_exact_tickets(self):
        for side in (0, 1):
            with self.subTest(side=side):
                self.mt.order_send.reset_mock()
                active = self.simulate(side)
                with patch('bot.direction', return_value=side), patch('bot.time.sleep') as sleep:
                    bot.run(self.mt, self.args)
                calls = [c.args[0] for c in self.mt.order_send.call_args_list]
                self.assertEqual(len(calls), 20)
                self.assertTrue(all(c['type'] == side and c['volume'] == .01 for c in calls[:10]))
                self.assertEqual([c['position'] for c in calls[10:]], list(range(1, 11)))
                self.assertTrue(all(c['type'] == 1-side for c in calls[10:]))
                sleep.assert_called_once_with(5)
                self.assertFalse(active)

    def test_failed_fourth_entry_closes_first_three(self):
        active = self.simulate(fail_open=4)
        with patch('bot.direction', return_value=0), self.assertRaisesRegex(RuntimeError, 'Order incomplete'):
            bot.run(self.mt, self.args)
        self.assertFalse(active)
        self.assertEqual(self.mt.order_send.call_count, 7)

    def test_rejected_close_does_not_skip_other_positions(self):
        active = self.simulate(fail_close=3)
        with patch('bot.direction', return_value=0), patch('bot.time.sleep'), self.assertRaisesRegex(RuntimeError, 'cleanup incomplete'):
            bot.run(self.mt, self.args)
        self.assertEqual([p.ticket for p in active], [3])
        self.assertEqual(self.mt.order_send.call_count, 20)

    def test_interrupt_closes_whole_batch(self):
        active = self.simulate()
        with patch('bot.direction', return_value=0), patch('bot.time.sleep', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            bot.run(self.mt, self.args)
        self.assertFalse(active)

    def test_wrong_account_and_netting_never_trade(self):
        for field, value in [('login', 999), ('margin_mode', 0)]:
            account = self.mt.account_info.return_value
            old = getattr(account, field)
            setattr(account, field, value)
            with self.assertRaises(RuntimeError):
                bot.run(self.mt, self.args)
            self.mt.order_send.assert_not_called()
            setattr(account, field, old)

    @patch('bot.time.time', return_value=200)
    def test_m1_direction_uses_completed_candles(self, clock):
        for closes, expected in [((10, 11), 0), ((11, 10), 1), ((10, 10), None)]:
            self.mt.copy_rates_from_pos.return_value = [dict(time=60, close=closes[0]), dict(time=120, close=closes[1])]
            self.assertEqual(bot.direction(self.mt, 'XAUUSDm'), expected)
            self.mt.copy_rates_from_pos.assert_called_with('XAUUSDm', 1, 1, 2)

    @patch('bot.time.time', return_value=1000)
    def test_stale_or_missing_candles_stop(self, clock):
        for bars in (None, [], [dict(time=60, close=10), dict(time=120, close=11)]):
            self.mt.copy_rates_from_pos.return_value = bars
            with self.assertRaises(RuntimeError):
                bot.direction(self.mt, 'XAUUSDm')
