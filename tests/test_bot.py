import argparse
import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch
import urllib.error

import main
from scripts import notify_telegram as bot
from scripts.logging_utils import SecretFilter


def encoded(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip('=')


class ParsingTests(unittest.TestCase):
    def test_plain_subscription_comments_bom_duplicates(self):
        text = '\ufeff#profile-title: test\nvless://a@host:443#one\nvless://a@host:443#two\ninvalid\n'
        self.assertEqual(main.parse_subscription(text), ['vless://a@host:443#one'])

    def test_base64_subscription_without_padding(self):
        self.assertEqual(main.parse_subscription(encoded('vless://a@host:443')), ['vless://a@host:443'])

    def test_target_protocols(self):
        fixtures = [
            ('vless://id@[2001:db8::1]:443?type=ws', ('2001:db8::1', 443)),
            ('trojan://password@example.org:8443#name', ('example.org', 8443)),
            ('vmess://' + encoded(json.dumps({'add': 'example.org', 'port': '443'})), ('example.org', 443)),
            ('ss://' + encoded('aes-256-gcm:password') + '@example.org:8388', ('example.org', 8388)),
            ('ss://' + encoded('aes-256-gcm:password@example.org:8388'), ('example.org', 8388)),
            ('ssr://' + encoded('example.org:8388:origin:aes-256-cfb:plain:cGFzcw/?remarks=a'), ('example.org', 8388)),
        ]
        for uri, expected in fixtures:
            with self.subTest(uri=uri):
                self.assertEqual(main.extract_target(uri, '1'), expected)

    def test_bad_and_udp_uris_skipped(self):
        for uri in ('vmess://garbage', 'vmess://' + encoded('[]'), 'vless://id@host:65536',
                    'vless://id@host:nope', 'vless://id@[bad]:443', 'hy2://id@host:443',
                    'tuic://id@host:443', 'ssr://' + encoded('invalid')):
            with self.subTest(uri=uri):
                self.assertEqual(main.extract_target(uri, '1'), (None, None))

    def test_mtproto_parameter_order_and_encoded_ipv6(self):
        for uri in ('tg://proxy?port=443&secret=abc&server=%5B2001%3Adb8%3A%3A1%5D',
                    'https://t.me/proxy?secret=abc&port=443&server=%5B2001%3Adb8%3A%3A1%5D'):
            self.assertEqual(main.extract_target(uri, '2'), ('2001:db8::1', 443))
        self.assertEqual(main.extract_target('https://evil.test/proxy?server=host&port=443', '2'), (None, None))

    def test_groups_count_utf16(self):
        groups = bot.pack_groups(['😀' * 1000, '😀' * 1000, 'x'])
        self.assertEqual(len(groups), 2)
        for group in groups:
            self.assertLessEqual(len('\n'.join(group).encode('utf-16-le')) // 2, 3600)
        self.assertEqual([len(group) for group in bot.pack_groups(['x'] * 21)], [10, 10, 1])


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_unique_endpoints_and_bounded_workers(self):
        active = peak = 0
        calls = []

        async def probe(uri, host, port, sem):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append((host, port))
            await asyncio.sleep(0)
            active -= 1
            return uri, host, 10

        lines = [f'vless://id@host{i}:443' for i in range(25)] + ['trojan://pw@host0:443']
        with patch.object(main, 'tcp_ping', side_effect=probe), patch.object(main, 'CONCURRENCY_LIMIT', 3):
            results = await main.test_targets(lines, '1')
        self.assertEqual(len(calls), 25)
        self.assertEqual(len(results), 26)
        self.assertLessEqual(peak, 3)

    async def test_ping_connection_failure(self):
        with patch.object(main.asyncio, 'open_connection', AsyncMock(side_effect=OSError('refused'))):
            self.assertIsNone((await main.tcp_ping('uri', 'host', 443, asyncio.Semaphore(1)))[2])

    async def test_close_failure_does_not_discard_connection_result(self):
        writer = Mock()
        writer.wait_closed = AsyncMock(side_effect=OSError())
        with patch.object(main.asyncio, 'open_connection', AsyncMock(return_value=(None, writer))):
            result = await main.tcp_ping('uri', 'host', 443, asyncio.Semaphore(1))
        self.assertIsNotNone(result[2])
        writer.close.assert_called_once()


class StateTests(unittest.TestCase):
    def test_legacy_subscribers_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'subscribers.json'
            path.write_text('[123, 456]')
            with patch.object(bot, 'SUBSCRIBERS_FILE', str(path)):
                self.assertEqual(bot.load_subscribers(), {'123': 'N/A', '456': 'N/A'})
                bot.save_subscribers({'123': 'name'})
                self.assertEqual(json.loads(path.read_text()), {'123': 'name'})
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_corrupted_database_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'subscribers.json'
            path.write_text('{broken')
            with patch.object(bot, 'SUBSCRIBERS_FILE', str(path)), self.assertRaises(ValueError):
                bot.load_subscribers()
            self.assertEqual(path.read_text(), '{broken')

    def test_atomic_write_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'out.txt'
            path.write_text('old')
            with patch.object(main.os, 'replace', side_effect=OSError('disk error')), self.assertRaises(OSError):
                main.atomic_write(str(path), 'new')
            self.assertEqual(path.read_text(), 'old')
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_secret_filter(self):
        record = logging.LogRecord('test', logging.ERROR, '', 0, 'failed %s %s', ('token', 'password'), None)
        with patch.dict(os.environ, TELEGRAM_BOT_TOKEN='token', DB_PASSWORD='password'):
            SecretFilter().filter(record)
        self.assertEqual(record.getMessage(), 'failed [REDACTED] [REDACTED]')


class ApiTests(unittest.TestCase):
    def test_rate_limit_then_success(self):
        rate_limit = urllib.error.HTTPError('url', 429, 'rate limit', {}, io.BytesIO(b'{"parameters":{"retry_after":2}}'))
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"ok":true}'
        with patch.object(bot.urllib.request, 'urlopen', side_effect=[rate_limit, response]) as request, patch.object(bot.time, 'sleep') as sleep:
            self.assertTrue(bot._post('sendMessage', b'{}', {}, 15)['ok'])
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_permanent_failure_not_retried(self):
        error = urllib.error.HTTPError('url', 403, 'forbidden', {}, io.BytesIO(b'{}'))
        with patch.object(bot.urllib.request, 'urlopen', side_effect=error) as request, patch.object(bot.time, 'sleep') as sleep:
            self.assertEqual(bot._post('sendMessage', b'{}', {}, 15)['error_code'], 403)
        request.assert_called_once()
        sleep.assert_not_called()

    def test_network_failure_bounded_retries(self):
        with patch.object(bot.urllib.request, 'urlopen', side_effect=OSError('down')) as request, patch.object(bot.time, 'sleep') as sleep:
            self.assertFalse(bot._post('sendMessage', b'{}', {}, 15)['ok'])
        self.assertEqual(request.call_count, 4)
        self.assertEqual(sleep.call_count, 3)

    def test_membership_restricted_and_configured_admin(self):
        with patch.object(bot, 'TELEGRAM_ADMIN_CHAT_ID', '42'), patch.object(bot, '_post') as post:
            self.assertTrue(bot.is_user_member(42))
            post.assert_not_called()
            post.return_value = {'ok': True, 'result': {'status': 'restricted', 'is_member': True}}
            self.assertTrue(bot.is_user_member(99))
            post.return_value = {'ok': False}
            self.assertFalse(bot.is_user_member(99))


class PollTests(unittest.TestCase):
    def test_commands_whitespace_and_state_saved_before_offset(self):
        updates = [
            {"update_id": 1, "message": {"chat": {"id": 7}, "from": {"id": 7}, "text": "/start@mybot"}},
            {"update_id": 2, "message": {"chat": {"id": 8}, "from": {"id": 8}, "text": "   "}},
            {"update_id": 3, "message": {"chat": {"id": 9}, "from": {"id": 9}, "text": "/start_extra"}},
            {"update_id": 4, "message": {"chat": {"id": 10}, "from": {"id": 10}, "text": "/stop"}},
        ]
        saved = []
        with patch.object(bot, "TELEGRAM_BOT_TOKEN", "test"), patch.object(bot, "load_offset", return_value=1), \
             patch.object(bot, "load_subscribers", return_value={"10": "old"}), \
             patch.object(bot, "_post", return_value={"ok": True, "result": updates}), \
             patch.object(bot, "is_user_member", return_value=True), patch.object(bot, "send_message", return_value={"ok": True}), \
             patch.object(bot, "save_subscribers", side_effect=lambda data: saved.append(("subs", data))), \
             patch.object(bot, "save_offset", side_effect=lambda value: saved.append(("offset", value))):
            bot.poll_updates()
        self.assertEqual(saved, [("subs", {"7": "N/A"}), ("offset", 5)])

    def test_failed_poll_does_not_advance_offset(self):
        with patch.object(bot, "TELEGRAM_BOT_TOKEN", "test"), patch.object(bot, "load_offset", return_value=10), \
             patch.object(bot, "_post", return_value={"ok": False}), patch.object(bot, "save_offset") as save:
            bot.poll_updates()
        save.assert_not_called()


class DeliveryTests(unittest.TestCase):
    def run_broadcast(self, folder, send, document):
        with patch.object(bot, 'TELEGRAM_BOT_TOKEN', 'test'), patch.object(bot, 'TELEGRAM_ADMIN_CHAT_ID', '42'), \
             patch.object(bot, 'load_subscribers', return_value={'42': 'Admin'}), \
             patch.object(bot, 'send_message', send), patch.object(bot, 'send_document', document), patch.object(bot.time, 'sleep'):
            bot.notify('Config', folder, 'config', limit=50)

    def test_html_escaping(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '2026-11-02_config.txt').write_text('vless://id@host:443?x=a&y=<b>#`label`')
            send = Mock(return_value={'ok': True})
            self.run_broadcast(directory, send, Mock())
            text = send.call_args_list[0].args[1]
            self.assertIn('&amp;', text)
            self.assertIn('&lt;b&gt;', text)
            self.assertEqual(send.call_args_list[0].kwargs['parse_mode'], 'HTML')
            self.assertIn('موفق: 1', send.call_args_list[-1].args[1])

    def test_failed_document_not_reported_as_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '2026-11-02_config.txt').write_text('vless://id@host:443?x=' + 'a' * 4000)
            send = Mock(return_value={'ok': True})
            document = Mock(return_value={'ok': False})
            self.run_broadcast(directory, send, document)
            self.assertIn('موفق: 0', send.call_args_list[-1].args[1])
            self.assertIn('ناموفق: 1', send.call_args_list[-1].args[1])
            self.assertIn('#@sentencedIntoMusic', document.call_args.kwargs['content'])

    def test_failed_recipient_does_not_stop_broadcast(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, '2026-11-02_proxy.txt').write_text('tg://proxy?server=host&port=443&secret=abc')
            send = Mock(side_effect=[{'ok': False}, {'ok': True}, {'ok': True}])
            with patch.object(bot, 'TELEGRAM_BOT_TOKEN', 'test'), patch.object(bot, 'TELEGRAM_ADMIN_CHAT_ID', '42'), \
                 patch.object(bot, 'load_subscribers', return_value={'1': 'user', '42': 'admin'}), \
                 patch.object(bot, 'is_user_member', return_value=True), patch.object(bot, 'send_message', send), patch.object(bot.time, 'sleep'):
                bot.notify('Proxy', directory, 'proxy')
            self.assertEqual(send.call_count, 3)
            self.assertIn('ناموفق: 1', send.call_args_list[-1].args[1])


class ExportTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_limit_applies_below_100_and_preserves_history(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path('config').mkdir()
                Path('config/old.txt').write_text('old')
                args = argparse.Namespace(mode='1', source='3', input='', export='1', locations=False)
                with patch.object(main, 'parse_args', return_value=args), patch.object(main, 'fetch_data', return_value=['x']), \
                     patch.object(main, 'test_targets', AsyncMock(return_value=[('vless://a@host:443', 'host', 20), ('vless://b@host:443', 'host', 10)])):
                    self.assertEqual(await main.main(), 0)
                output = next(Path('config').glob('*_config.txt')).read_text().splitlines()
                self.assertEqual(output, ['vless://b@host:443'])
                self.assertEqual(Path('config/old.txt').read_text(), 'old')
            finally:
                os.chdir(original)

    async def test_fetch_failure_returns_nonzero(self):
        args = argparse.Namespace(mode='1', source='3', input='', export='all', locations=False)
        with patch.object(main, 'parse_args', return_value=args), patch.object(main, 'fetch_data', side_effect=OSError('network down')):
            self.assertEqual(await main.main(), 1)


if __name__ == '__main__':
    unittest.main()
